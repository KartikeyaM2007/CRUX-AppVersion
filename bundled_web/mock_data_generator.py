import os
import pandas as pd
import numpy as np
import random
from datetime import datetime, timedelta

def generate_mock_financial_data(num_rows=1000, output_path="data/raw_transactions.csv"):
    """
    Generates a mock financial dataset with intentional missing values and errors
    to simulate real-world 'dirty' tabular data that needs to be repaired.
    """
    np.random.seed(42)
    random.seed(42)

    data = []
    
    merchants = {
        "Walmart": "Retail",
        "Target": "Retail",
        "Amazon": "E-commerce",
        "Netflix": "Entertainment",
        "Uber": "Transport",
        "Shell": "Gas Station",
        "Starbucks": "Food & Beverage",
        "McDonalds": "Food & Beverage"
    }
    merchant_names = list(merchants.keys())
    
    start_date = datetime(2023, 1, 1)

    for i in range(num_rows):
        # Generate base data
        txn_id = f"TXN_{10000 + i}"
        merchant_name = random.choice(merchant_names)
        merchant_category = merchants[merchant_name]
        
        # Continuous values
        amount = np.random.lognormal(mean=3.5, sigma=1.0)
        amount = round(amount, 2)
        
        # Fraud flag (highly imbalanced: ~3% fraud)
        is_fraud = 1 if random.random() < 0.03 else 0
        
        if is_fraud:
            # Fraudulent transactions tend to have higher amounts
            amount = amount * random.uniform(2.0, 5.0)
            
        # Timestamp
        days_offset = random.randint(0, 365)
        txn_date = start_date + timedelta(days=days_offset)
        
        # User ID
        user_id = f"USR_{random.randint(100, 500)}"
        
        # INTENTIONAL CORRUPTIONS (The "Dirty" aspect)
        
        # 1. Missing categorical values (LLM will need to infer Category from Merchant Name)
        if random.random() < 0.15:  # 15% chance
            merchant_category = np.nan
            
        # 2. Corrupted amounts (e.g., negative amounts that shouldn't exist)
        if random.random() < 0.05:  # 5% chance
            amount = -abs(amount)
            
        # 3. Missing User IDs
        if random.random() < 0.05:
            user_id = np.nan
            
        data.append({
            "transaction_id": txn_id,
            "date": txn_date.strftime("%Y-%m-%d"),
            "user_id": user_id,
            "merchant_name": merchant_name,
            "merchant_category": merchant_category,
            "amount": amount,
            "is_fraud": is_fraud
        })

    df = pd.DataFrame(data)
    
    # Save to CSV
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    df.to_csv(output_path, index=False)
    print(f"Generated {num_rows} rows of dirty mock data to {output_path}")
    print("\nSample Data with Missing Values:")
    print(df[df.isnull().any(axis=1)].head())
    
    return df

if __name__ == "__main__":
    generate_mock_financial_data(5000)
