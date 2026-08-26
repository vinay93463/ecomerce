from fastapi import (
    FastAPI,
    Request,
    UploadFile,
    File,
    Form
)

from fastapi.responses import (
    RedirectResponse,
    JSONResponse
)

from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from sqlalchemy.orm import Session

from sqlalchemy import text, inspect

from starlette.middleware.sessions import SessionMiddleware

import hashlib
import hmac
import secrets
import os
import shutil
import uuid


from database import (
    Base,
    engine,
    SessionLocal
)

from models.product import Product
from models.cart import CartItem
from models.order import Order
from models.order_item import OrderItem
from models.user import User


# =========================================================
# DATABASE
# =========================================================

Base.metadata.create_all(bind=engine)


# =========================================================
# CART DATABASE MIGRATION
# =========================================================
# Adds user_id to an existing cart_items table if necessary.
# This prevents the old database from crashing after the
# CartItem model was changed.
# =========================================================

def migrate_cart_table():

    try:

        inspector = inspect(engine)

        tables = inspector.get_table_names()

        if "cart_items" not in tables:
            return

        columns = [
            column["name"]
            for column in inspector.get_columns(
                "cart_items"
            )
        ]

        if "user_id" not in columns:

            with engine.begin() as connection:

                connection.execute(
                    text(
                        "ALTER TABLE cart_items "
                        "ADD COLUMN user_id INTEGER"
                    )
                )

            print(
                "Database updated: cart_items.user_id added."
            )

    except Exception as error:

        print(
            "Cart migration warning:",
            repr(error)
        )


migrate_cart_table()


# =========================================================
# FASTAPI APP
# =========================================================

app = FastAPI(
    title="MyStore E-Commerce API",
    version="1.0.0"
)


# =========================================================
# SESSION
# =========================================================

app.add_middleware(
    SessionMiddleware,
    secret_key="mystore-secret-key-change-this"
)


# =========================================================
# PASSWORD HASHING
# =========================================================

PASSWORD_ITERATIONS = 600_000


def hash_password(password: str) -> str:

    salt = secrets.token_bytes(16)

    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS
    )

    return (
        "pbkdf2_sha256$"
        + str(PASSWORD_ITERATIONS)
        + "$"
        + salt.hex()
        + "$"
        + password_hash.hex()
    )


def verify_password(
    password: str,
    stored_password: str
) -> bool:

    try:

        scheme, iterations, salt_hex, hash_hex = (
            stored_password.split("$", 3)
        )

        if scheme != "pbkdf2_sha256":
            return False

        salt = bytes.fromhex(salt_hex)

        expected_hash = bytes.fromhex(
            hash_hex
        )

        actual_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            int(iterations)
        )

        return hmac.compare_digest(
            actual_hash,
            expected_hash
        )

    except (
        ValueError,
        TypeError
    ):

        return False


# =========================================================
# STATIC FILES
# =========================================================

app.mount(
    "/static",
    StaticFiles(
        directory="static"
    ),
    name="static"
)


# =========================================================
# TEMPLATES
# =========================================================

templates = Jinja2Templates(
    directory="templates"
)


# =========================================================
# HELPERS
# =========================================================

def get_logged_in_user_id(
    request: Request
):

    user_id = request.session.get(
        "user_id"
    )

    if not user_id:
        return None

    try:

        return int(user_id)

    except (
        TypeError,
        ValueError
    ):

        return None


def require_login(
    request: Request
):

    user_id = get_logged_in_user_id(
        request
    )

    if not user_id:

        return JSONResponse(
            status_code=401,
            content={
                "message":
                    "Please login first."
            }
        )

    return user_id


# =========================================================
# HOME PAGE
# =========================================================

@app.get("/")
def home(request: Request):

    db: Session = SessionLocal()

    try:

        products = db.query(
            Product
        ).all()

        return templates.TemplateResponse(
            request=request,
            name="home.html",
            context={
                "products": products
            }
        )

    finally:

        db.close()


# =========================================================
# CREATE PRODUCT
# =========================================================

@app.post("/products")
def create_product(
    name: str = Form(...),
    description: str = Form(...),
    price: float = Form(...),
    stock: int = Form(...),
    category: str = Form("General"),
    image: UploadFile | None = File(None)
):

    db: Session = SessionLocal()

    try:

        if not name.strip():

            return JSONResponse(
                status_code=400,
                content={
                    "message":
                        "Product name is required."
                }
            )

        if price < 0:

            return JSONResponse(
                status_code=400,
                content={
                    "message":
                        "Price cannot be negative."
                }
            )

        if stock < 0:

            return JSONResponse(
                status_code=400,
                content={
                    "message":
                        "Stock cannot be negative."
                }
            )

        image_path = ""

        os.makedirs(
            "static/images",
            exist_ok=True
        )

        if image and image.filename:

            allowed_types = [
                "image/jpeg",
                "image/png",
                "image/webp",
                "image/gif"
            ]

            if image.content_type not in allowed_types:

                return JSONResponse(
                    status_code=400,
                    content={
                        "message":
                            "Only JPG, PNG, WEBP or GIF images are allowed."
                    }
                )

            extension = os.path.splitext(
                image.filename
            )[1].lower()

            allowed_extensions = [
                ".jpg",
                ".jpeg",
                ".png",
                ".webp",
                ".gif"
            ]

            if extension not in allowed_extensions:

                return JSONResponse(
                    status_code=400,
                    content={
                        "message":
                            "Invalid image extension."
                    }
                )

            filename = (
                "product_"
                + uuid.uuid4().hex
                + extension
            )

            filepath = os.path.join(
                "static",
                "images",
                filename
            )

            with open(
                filepath,
                "wb"
            ) as buffer:

                shutil.copyfileobj(
                    image.file,
                    buffer
                )

            image_path = (
                "/static/images/"
                + filename
            )

        product = Product(
            name=name.strip(),
            description=description.strip(),
            price=price,
            stock=stock,
            category=(
                category.strip()
                or "General"
            ),
            image=image_path
        )

        db.add(product)

        db.commit()

        db.refresh(product)

        return product

    except Exception as error:

        db.rollback()

        return JSONResponse(
            status_code=500,
            content={
                "message":
                    "Unable to create product.",
                "detail":
                    str(error)
            }
        )

    finally:

        db.close()


# =========================================================
# GET ALL PRODUCTS
# =========================================================

@app.get("/products")
def get_products():

    db: Session = SessionLocal()

    try:

        return db.query(
            Product
        ).all()

    finally:

        db.close()


# =========================================================
# GET ONE PRODUCT
# =========================================================

@app.get("/products/{product_id}")
def get_product(
    product_id: int
):

    db: Session = SessionLocal()

    try:

        product = db.query(
            Product
        ).filter(
            Product.id == product_id
        ).first()

        if product is None:

            return JSONResponse(
                status_code=404,
                content={
                    "message":
                        "Product not found."
                }
            )

        return product

    finally:

        db.close()


# =========================================================
# UPDATE PRODUCT
# =========================================================

@app.put("/products/{product_id}")
def update_product(
    product_id: int,
    name: str,
    description: str,
    price: float,
    stock: int,
    category: str = "General",
    image: str = ""
):

    db: Session = SessionLocal()

    try:

        product = db.query(
            Product
        ).filter(
            Product.id == product_id
        ).first()

        if product is None:

            return JSONResponse(
                status_code=404,
                content={
                    "message":
                        "Product not found."
                }
            )

        if price < 0:

            return JSONResponse(
                status_code=400,
                content={
                    "message":
                        "Price cannot be negative."
                }
            )

        if stock < 0:

            return JSONResponse(
                status_code=400,
                content={
                    "message":
                        "Stock cannot be negative."
                }
            )

        product.name = name.strip()

        product.description = (
            description.strip()
        )

        product.price = price

        product.stock = stock

        product.category = (
            category.strip()
            or "General"
        )

        if image:

            product.image = image

        db.commit()

        db.refresh(product)

        return product

    except Exception as error:

        db.rollback()

        return JSONResponse(
            status_code=500,
            content={
                "message":
                    "Unable to update product.",
                "detail":
                    str(error)
            }
        )

    finally:

        db.close()


# =========================================================
# DELETE PRODUCT
# =========================================================

@app.delete("/products/{product_id}")
def delete_product(
    product_id: int
):

    db: Session = SessionLocal()

    try:

        product = db.query(
            Product
        ).filter(
            Product.id == product_id
        ).first()

        if product is None:

            return JSONResponse(
                status_code=404,
                content={
                    "message":
                        "Product not found."
                }
            )

        # Remove this product from every cart.
        db.query(
            CartItem
        ).filter(
            CartItem.product_id ==
            product_id
        ).delete(
            synchronize_session=False
        )

        db.delete(product)

        db.commit()

        return {
            "message":
                "Product deleted successfully."
        }

    except Exception as error:

        db.rollback()

        return JSONResponse(
            status_code=500,
            content={
                "message":
                    "Unable to delete product.",
                "detail":
                    str(error)
            }
        )

    finally:

        db.close()


# =========================================================
# PRODUCTS PAGE
# =========================================================

@app.get("/products-page")
def products_page(
    request: Request
):

    return templates.TemplateResponse(
        request=request,
        name="products.html",
        context={}
    )


# =========================================================
# PRODUCT SEARCH
# =========================================================

@app.get("/products-search")
def search_products(
    q: str = "",
    category: str = "",
    sort: str = "",
    page: int = 1,
    limit: int = 10
):

    db: Session = SessionLocal()

    try:

        page = max(
            page,
            1
        )

        limit = max(
            min(limit, 100),
            1
        )

        query = db.query(
            Product
        )

        if q:

            query = query.filter(
                Product.name.ilike(
                    f"%{q}%"
                )
            )

        if category:

            query = query.filter(
                Product.category ==
                category
            )

        if sort == "price_low":

            query = query.order_by(
                Product.price.asc()
            )

        elif sort == "price_high":

            query = query.order_by(
                Product.price.desc()
            )

        elif sort == "stock_low":

            query = query.order_by(
                Product.stock.asc()
            )

        elif sort == "stock_high":

            query = query.order_by(
                Product.stock.desc()
            )

        total = query.count()

        total_pages = (
            total + limit - 1
        ) // limit

        offset = (
            page - 1
        ) * limit

        products = query.offset(
            offset
        ).limit(
            limit
        ).all()

        return {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": total_pages,
            "count": len(products),
            "products": products
        }

    finally:

        db.close()


# =========================================================
# ADD TO CART
# =========================================================

@app.post("/cart")
def add_to_cart(
    request: Request,
    product_id: int,
    quantity: int = 1
):

    user_id = get_logged_in_user_id(
        request
    )

    if not user_id:

        return JSONResponse(
            status_code=401,
            content={
                "message":
                    "Please login before adding products to your cart."
            }
        )

    db: Session = SessionLocal()

    try:

        if quantity <= 0:

            return JSONResponse(
                status_code=400,
                content={
                    "message":
                        "Quantity must be at least 1."
                }
            )

        product = db.query(
            Product
        ).filter(
            Product.id == product_id
        ).first()

        if product is None:

            return JSONResponse(
                status_code=404,
                content={
                    "message":
                        "Product not found."
                }
            )

        if product.stock <= 0:

            return JSONResponse(
                status_code=400,
                content={
                    "message":
                        "Product is out of stock."
                }
            )

        # IMPORTANT:
        # Find cart item belonging to THIS user.
        cart_item = db.query(
            CartItem
        ).filter(
            CartItem.user_id == user_id,
            CartItem.product_id == product_id
        ).first()

        if cart_item:

            new_quantity = (
                cart_item.quantity
                + quantity
            )

            if new_quantity > product.stock:

                return JSONResponse(
                    status_code=400,
                    content={
                        "message":
                            "Not enough stock."
                    }
                )

            cart_item.quantity = (
                new_quantity
            )

        else:

            if quantity > product.stock:

                return JSONResponse(
                    status_code=400,
                    content={
                        "message":
                            "Not enough stock."
                    }
                )

            cart_item = CartItem(
                user_id=user_id,
                product_id=product_id,
                quantity=quantity
            )

            db.add(cart_item)

        db.commit()

        db.refresh(cart_item)

        return {
            "message":
                "Product added to cart.",
            "cart_item_id":
                cart_item.id,
            "product_id":
                product_id,
            "quantity":
                cart_item.quantity
        }

    except Exception as error:

        db.rollback()

        print(
            "ADD TO CART ERROR:",
            repr(error)
        )

        return JSONResponse(
            status_code=500,
            content={
                "message":
                    "Unable to add product to cart.",
                "detail":
                    str(error)
            }
        )

    finally:

        db.close()


# =========================================================
# GET CART
# =========================================================

@app.get("/cart")
def get_cart(
    request: Request
):

    user_id = get_logged_in_user_id(
        request
    )

    if not user_id:

        return JSONResponse(
            status_code=401,
            content={
                "message":
                    "Please login to view your cart."
            }
        )

    db: Session = SessionLocal()

    try:

        cart_items = db.query(
            CartItem
        ).filter(
            CartItem.user_id == user_id
        ).all()

        cart = []

        stale_items = []

        for item in cart_items:

            product = db.query(
                Product
            ).filter(
                Product.id ==
                item.product_id
            ).first()

            if product is None:

                stale_items.append(item)

                continue

            cart.append({
                "cart_item_id":
                    item.id,

                "product_id":
                    product.id,

                "name":
                    product.name,

                "price":
                    product.price,

                "quantity":
                    item.quantity,

                "subtotal":
                    product.price *
                    item.quantity
            })

        # Automatically remove stale cart items.
        for item in stale_items:

            db.delete(item)

        if stale_items:

            db.commit()

        total = sum(
            item["subtotal"]
            for item in cart
        )

        return {
            "items": cart,
            "total": total
        }

    finally:

        db.close()


# =========================================================
# REMOVE FROM CART
# =========================================================

@app.delete("/cart/{cart_item_id}")
def remove_from_cart(
    request: Request,
    cart_item_id: int
):

    user_id = get_logged_in_user_id(
        request
    )

    if not user_id:

        return JSONResponse(
            status_code=401,
            content={
                "message":
                    "Please login first."
            }
        )

    db: Session = SessionLocal()

    try:

        cart_item = db.query(
            CartItem
        ).filter(
            CartItem.id == cart_item_id,
            CartItem.user_id == user_id
        ).first()

        if cart_item is None:

            return JSONResponse(
                status_code=404,
                content={
                    "message":
                        "Cart item not found."
                }
            )

        db.delete(cart_item)

        db.commit()

        return {
            "message":
                "Product removed from cart."
        }

    finally:

        db.close()


# =========================================================
# UPDATE CART QUANTITY
# =========================================================

@app.put("/cart/{cart_item_id}")
def update_cart_quantity(
    request: Request,
    cart_item_id: int,
    quantity: int
):

    user_id = get_logged_in_user_id(
        request
    )

    if not user_id:

        return JSONResponse(
            status_code=401,
            content={
                "message":
                    "Please login first."
            }
        )

    db: Session = SessionLocal()

    try:

        if quantity <= 0:

            return JSONResponse(
                status_code=400,
                content={
                    "message":
                        "Quantity must be greater than 0."
                }
            )

        cart_item = db.query(
            CartItem
        ).filter(
            CartItem.id == cart_item_id,
            CartItem.user_id == user_id
        ).first()

        if cart_item is None:

            return JSONResponse(
                status_code=404,
                content={
                    "message":
                        "Cart item not found."
                }
            )

        product = db.query(
            Product
        ).filter(
            Product.id ==
            cart_item.product_id
        ).first()

        if product is None:

            db.delete(cart_item)

            db.commit()

            return JSONResponse(
                status_code=404,
                content={
                    "message":
                        "Product no longer exists. Cart item removed."
                }
            )

        if quantity > product.stock:

            return JSONResponse(
                status_code=400,
                content={
                    "message":
                        "Not enough stock."
                }
            )

        cart_item.quantity = quantity

        db.commit()

        db.refresh(cart_item)

        return {
            "message":
                "Cart quantity updated.",
            "cart_item_id":
                cart_item.id,
            "product_id":
                cart_item.product_id,
            "quantity":
                cart_item.quantity
        }

    finally:

        db.close()


# =========================================================
# CART PAGE
# =========================================================

@app.get("/cart-page")
def cart_page(
    request: Request
):

    return templates.TemplateResponse(
        request=request,
        name="cart.html",
        context={}
    )


# =========================================================
# PRODUCT DETAIL PAGE
# =========================================================

@app.get("/product-page/{product_id}")
def product_page(
    product_id: int,
    request: Request
):

    db: Session = SessionLocal()

    try:

        product = db.query(
            Product
        ).filter(
            Product.id == product_id
        ).first()

        if product is None:

            return templates.TemplateResponse(
                request=request,
                name="product.html",
                context={
                    "product": None,
                    "error":
                        "Product not found."
                },
                status_code=404
            )

        return templates.TemplateResponse(
            request=request,
            name="product.html",
            context={
                "product": product
            }
        )

    finally:

        db.close()


# =========================================================
# CHECKOUT PAGE
# =========================================================

@app.get("/checkout-page")
def checkout_page(
    request: Request
):

    if not get_logged_in_user_id(
        request
    ):

        return RedirectResponse(
            url="/login",
            status_code=303
        )

    return templates.TemplateResponse(
        request=request,
        name="checkout.html",
        context={}
    )


# =========================================================
# CREATE ORDER
# =========================================================

@app.post("/orders")
def create_order(
    request: Request,
    address: str = Form(...)
):

    user_id = get_logged_in_user_id(
        request
    )

    if not user_id:

        return JSONResponse(
            status_code=401,
            content={
                "message":
                    "Please login before placing an order."
            }
        )

    address = address.strip()

    if not address:

        return JSONResponse(
            status_code=400,
            content={
                "message":
                    "Delivery address is required."
            }
        )

    db: Session = SessionLocal()

    try:

        user = db.query(
            User
        ).filter(
            User.id == user_id
        ).first()

        if user is None:

            return JSONResponse(
                status_code=404,
                content={
                    "message":
                        "Customer account not found."
                }
            )

        # IMPORTANT:
        # Only this customer's cart.
        cart_items = db.query(
            CartItem
        ).filter(
            CartItem.user_id == user_id
        ).all()

        if not cart_items:

            return JSONResponse(
                status_code=400,
                content={
                    "message":
                        "Cart is empty."
                }
            )

        products_for_order = []

        total = 0.0

        # ---------------------------------------------
        # CHECK EVERY CART ITEM
        # ---------------------------------------------

        for cart_item in cart_items:

            product = db.query(
                Product
            ).filter(
                Product.id ==
                cart_item.product_id
            ).first()

            if product is None:

                # Remove stale cart item.
                db.delete(cart_item)

                db.commit()

                return JSONResponse(
                    status_code=400,
                    content={
                        "message":
                            "A product in your cart no longer exists. "
                            "It has been removed from your cart. "
                            "Please return to your cart and try again."
                    }
                )

            if cart_item.quantity <= 0:

                return JSONResponse(
                    status_code=400,
                    content={
                        "message":
                            f"Invalid quantity for {product.name}."
                    }
                )

            if cart_item.quantity > product.stock:

                return JSONResponse(
                    status_code=400,
                    content={
                        "message":
                            f"Not enough stock for {product.name}. "
                            f"Available stock: {product.stock}."
                    }
                )

            subtotal = (
                product.price *
                cart_item.quantity
            )

            total += subtotal

            products_for_order.append(
                (
                    cart_item,
                    product
                )
            )

        # ---------------------------------------------
        # CREATE ORDER
        # ---------------------------------------------

        order = Order(
            customer_name=user.name,
            email=user.email,
            address=address,
            total=total,
            status="Pending"
        )

        db.add(order)

        db.flush()

        # ---------------------------------------------
        # ORDER ITEMS + STOCK
        # ---------------------------------------------

        for cart_item, product in (
            products_for_order
        ):

            order_item = OrderItem(
                order_id=order.id,
                product_id=product.id,
                quantity=cart_item.quantity,
                price=product.price
            )

            db.add(order_item)

            product.stock -= (
                cart_item.quantity
            )

            db.delete(cart_item)

        # ---------------------------------------------
        # SAVE
        # ---------------------------------------------

        db.commit()

        db.refresh(order)

        return {
            "message":
                "Order placed successfully!",
            "id":
                order.id,
            "order_id":
                order.id,
            "total":
                order.total,
            "status":
                order.status
        }

    except Exception as error:

        db.rollback()

        print(
            "========================================"
        )

        print(
            "ORDER CREATION ERROR:"
        )

        print(
            repr(error)
        )

        print(
            "========================================"
        )

        return JSONResponse(
            status_code=500,
            content={
                "message":
                    "Unable to place order.",
                "detail":
                    str(error)
            }
        )

    finally:

        db.close()


# =========================================================
# GET ORDERS
# =========================================================

@app.get("/orders")
def get_orders(
    request: Request
):

    user_id = get_logged_in_user_id(
        request
    )

    if not user_id:

        return JSONResponse(
            status_code=401,
            content={
                "message":
                    "Please login to view orders."
            }
        )

    db: Session = SessionLocal()

    try:

        # Order model currently has no user_id,
        # so orders are filtered by the user's email.
        user = db.query(
            User
        ).filter(
            User.id == user_id
        ).first()

        if user is None:

            return JSONResponse(
                status_code=404,
                content={
                    "message":
                        "Customer account not found."
                }
            )

        orders = db.query(
            Order
        ).filter(
            Order.email == user.email
        ).order_by(
            Order.id.desc()
        ).all()

        return orders

    finally:

        db.close()


# =========================================================
# ORDERS PAGE
# =========================================================

@app.get("/orders-page")
def orders_page(
    request: Request
):

    if not get_logged_in_user_id(
        request
    ):

        return RedirectResponse(
            url="/login",
            status_code=303
        )

    return templates.TemplateResponse(
        request=request,
        name="orders.html",
        context={}
    )


# =========================================================
# GET ORDER DETAILS
# =========================================================

@app.get("/orders/{order_id}")
def get_order(
    request: Request,
    order_id: int
):

    user_id = get_logged_in_user_id(
        request
    )

    if not user_id:

        return JSONResponse(
            status_code=401,
            content={
                "message":
                    "Please login first."
            }
        )

    db: Session = SessionLocal()

    try:

        user = db.query(
            User
        ).filter(
            User.id == user_id
        ).first()

        if user is None:

            return JSONResponse(
                status_code=404,
                content={
                    "message":
                        "Customer account not found."
                }
            )

        order = db.query(
            Order
        ).filter(
            Order.id == order_id,
            Order.email == user.email
        ).first()

        if order is None:

            return JSONResponse(
                status_code=404,
                content={
                    "message":
                        "Order not found."
                }
            )

        order_items = db.query(
            OrderItem
        ).filter(
            OrderItem.order_id ==
            order_id
        ).all()

        items = []

        for item in order_items:

            product = db.query(
                Product
            ).filter(
                Product.id ==
                item.product_id
            ).first()

            # Even if product was deleted later,
            # preserve order information as much as possible.
            items.append({
                "product_id":
                    item.product_id,

                "name":
                    product.name
                    if product
                    else "Product",

                "quantity":
                    item.quantity,

                "price":
                    item.price,

                "subtotal":
                    item.price *
                    item.quantity
            })

        return {
            "order_id":
                order.id,

            "customer_name":
                order.customer_name,

            "email":
                order.email,

            "address":
                order.address,

            "total":
                order.total,

            "status":
                order.status,

            "items":
                items
        }

    finally:

        db.close()


# =========================================================
# UPDATE ORDER STATUS
# =========================================================

@app.put("/orders/{order_id}/status")
def update_order_status(
    order_id: int,
    status: str
):

    db: Session = SessionLocal()

    try:

        order = db.query(
            Order
        ).filter(
            Order.id == order_id
        ).first()

        if order is None:

            return JSONResponse(
                status_code=404,
                content={
                    "message":
                        "Order not found."
                }
            )

        allowed_statuses = [
            "Pending",
            "Confirmed",
            "Shipped",
            "Delivered"
        ]

        if status not in allowed_statuses:

            return JSONResponse(
                status_code=400,
                content={
                    "message":
                        "Invalid status.",
                    "allowed_statuses":
                        allowed_statuses
                }
            )

        order.status = status

        db.commit()

        db.refresh(order)

        return {
            "message":
                "Order status updated successfully.",
            "order_id":
                order.id,
            "status":
                order.status
        }

    finally:

        db.close()


# =========================================================
# ADMIN LOGIN PAGE
# =========================================================

@app.get("/admin/login")
def admin_login_page(
    request: Request
):

    if request.session.get(
        "admin_logged_in"
    ):

        return RedirectResponse(
            url="/admin",
            status_code=303
        )

    return templates.TemplateResponse(
        request=request,
        name="admin_login.html",
        context={}
    )


# =========================================================
# ADMIN LOGIN
# =========================================================

@app.post("/admin/login")
def admin_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):

    if (
        username == "admin"
        and
        password == "admin123"
    ):

        request.session[
            "admin_logged_in"
        ] = True

        return RedirectResponse(
            url="/admin",
            status_code=303
        )

    return templates.TemplateResponse(
        request=request,
        name="admin_login.html",
        context={
            "error":
                "Invalid username or password."
        }
    )


# =========================================================
# ADMIN LOGOUT
# =========================================================

@app.get("/admin/logout")
def admin_logout(
    request: Request
):

    request.session.pop(
        "admin_logged_in",
        None
    )

    return RedirectResponse(
        url="/admin/login",
        status_code=303
    )


# =========================================================
# ADMIN PAGE
# =========================================================

@app.get("/admin")
def admin_page(
    request: Request
):

    if not request.session.get(
        "admin_logged_in"
    ):

        return RedirectResponse(
            url="/admin/login",
            status_code=303
        )

    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={}
    )


# =========================================================
# REGISTER PAGE
# =========================================================

@app.get("/register")
def register_page(
    request: Request
):

    return templates.TemplateResponse(
        request=request,
        name="register.html",
        context={}
    )


# =========================================================
# REGISTER
# =========================================================

@app.post("/register")
def register_user(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...)
):

    name = name.strip()

    email = email.strip().lower()

    db: Session = SessionLocal()

    try:

        if not name:

            return templates.TemplateResponse(
                request=request,
                name="register.html",
                context={
                    "error":
                        "Name is required."
                }
            )

        if len(password) < 6:

            return templates.TemplateResponse(
                request=request,
                name="register.html",
                context={
                    "error":
                        "Password must be at least 6 characters."
                }
            )

        existing_user = db.query(
            User
        ).filter(
            User.email == email
        ).first()

        if existing_user:

            return templates.TemplateResponse(
                request=request,
                name="register.html",
                context={
                    "error":
                        "Email already registered."
                }
            )

        user = User(
            name=name,
            email=email,
            password=hash_password(
                password
            )
        )

        db.add(user)

        db.commit()

        db.refresh(user)

        request.session[
            "user_id"
        ] = user.id

        request.session[
            "user_name"
        ] = user.name

        return RedirectResponse(
            url="/",
            status_code=303
        )

    except Exception as error:

        db.rollback()

        print(
            "REGISTER ERROR:",
            repr(error)
        )

        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={
                "error":
                    "Unable to create account."
            }
        )

    finally:

        db.close()


# =========================================================
# LOGIN PAGE
# =========================================================

@app.get("/login")
def login_page(
    request: Request
):

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={}
    )


# =========================================================
# LOGIN
# =========================================================

@app.post("/login")
def login_user(
    request: Request,
    email: str = Form(...),
    password: str = Form(...)
):

    email = email.strip().lower()

    db: Session = SessionLocal()

    try:

        user = db.query(
            User
        ).filter(
            User.email == email
        ).first()

        if not user:

            return templates.TemplateResponse(
                request=request,
                name="login.html",
                context={
                    "error":
                        "Invalid email or password."
                }
            )

        if not verify_password(
            password,
            user.password
        ):

            return templates.TemplateResponse(
                request=request,
                name="login.html",
                context={
                    "error":
                        "Invalid email or password."
                }
            )

        request.session[
            "user_id"
        ] = user.id

        request.session[
            "user_name"
        ] = user.name

        return RedirectResponse(
            url="/",
            status_code=303
        )

    finally:

        db.close()


# =========================================================
# CUSTOMER LOGOUT
# =========================================================

@app.get("/logout")
def logout_user(
    request: Request
):

    request.session.pop(
        "user_id",
        None
    )

    request.session.pop(
        "user_name",
        None
    )

    return RedirectResponse(
        url="/",
        status_code=303
    )