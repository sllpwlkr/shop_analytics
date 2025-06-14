from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
import logging
import uuid

from api.database import get_db
from api import schemas, models
from api.auth import get_current_user
from api.producers import send_customer
from api.schemas import CustomerBulkCreate, BulkResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import insert

router = APIRouter(prefix="/customers")
logger = logging.getLogger(__name__)

@router.post("/", response_model=schemas.CustomerOut)
async def create_customer(
    customer: schemas.CustomerCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    db_customer = models.Customer(
        first_name=customer.first_name,
        last_name=customer.last_name,
        email=customer.email,
        phone=customer.phone
    )
    
    db.add(db_customer)
    db.commit()
    db.refresh(db_customer)
    
    customer_data = {
        "customer_id": db_customer.customer_id,
        "first_name": db_customer.first_name,
        "last_name": db_customer.last_name,
        "email": db_customer.email,
        "phone": db_customer.phone,
        "created_at": db_customer.created_at.isoformat()
    }
    
    try:
        if "send_customer" in globals():
            await send_customer(customer_data)
    except Exception as e:
        logger.error(f"Failed to send customer to Kafka: {str(e)}")
    
    return db_customer

@router.get("/", response_model=List[schemas.CustomerOut])
async def read_customers(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    customers = db.query(models.Customer).offset(skip).limit(limit).all()
    return customers

@router.get("/{customer_id}", response_model=schemas.CustomerOut)
async def read_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    customer = db.query(models.Customer).filter(models.Customer.customer_id == customer_id).first()
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer

@router.put("/{customer_id}", response_model=schemas.CustomerOut)
async def update_customer(
    customer_id: int,
    customer: schemas.CustomerUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    db_customer = db.query(models.Customer).filter(models.Customer.customer_id == customer_id).first()
    if db_customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    if customer.first_name is not None:
        db_customer.first_name = customer.first_name
    if customer.last_name is not None:
        db_customer.last_name = customer.last_name
    if customer.email is not None:
        db_customer.email = customer.email
    if customer.phone is not None:
        db_customer.phone = customer.phone
    
    db.commit()
    db.refresh(db_customer)
    
    customer_data = {
        "customer_id": db_customer.customer_id,
        "first_name": db_customer.first_name,
        "last_name": db_customer.last_name,
        "email": db_customer.email,
        "phone": db_customer.phone,
        "created_at": db_customer.created_at.isoformat(),
        "operation": "update"
    }
    
    try:
        if "send_customer" in globals():
            await send_customer(customer_data)
    except Exception as e:
        logger.error(f"Failed to send customer update to Kafka: {str(e)}")
    
    return db_customer

@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    db_customer = db.query(models.Customer).filter(models.Customer.customer_id == customer_id).first()
    if db_customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    customer_data = {
        "customer_id": db_customer.customer_id,
        "operation": "delete"
    }
    
    try:
        if "send_customer" in globals():
            await send_customer(customer_data)
    except Exception as e:
        logger.error(f"Failed to send customer deletion to Kafka: {str(e)}")
    
    db.delete(db_customer)
    db.commit()
    
    return None

@router.post("/bulk-postgres", response_model=BulkResponse)
async def bulk_insert_customers(
    customers_data: CustomerBulkCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    success_count = 0
    errors = []
    
    existing_emails = {email[0] for email in db.query(models.Customer.email).all()}
    
    for idx, customer in enumerate(customers_data.customers):
        try:
            if customer.email in existing_emails:
                errors.append(f"Email already exists: {customer.email}")
                continue
                
            existing_emails.add(customer.email)
            
            db_customer = models.Customer(
                first_name=customer.first_name,
                last_name=customer.last_name,
                email=customer.email,
                phone=customer.phone
            )
            
            db.add(db_customer)
            success_count += 1
            
        except Exception as e:
            errors.append(f"Error at index {idx}: {str(e)}")
    
    if success_count > 0:
        try:
            db.commit()
        except IntegrityError as e:
            db.rollback()
            return {
                "success_count": 0,
                "error_count": 1,
                "errors": [f"Database integrity error: {str(e)}"]
            }
        except Exception as e:
            db.rollback()
            return {
                "success_count": 0,
                "error_count": 1,
                "errors": [f"Database error: {str(e)}"]
            }
    
    return {
        "success_count": success_count,
        "error_count": len(errors),
        "errors": errors if errors else None
    } 