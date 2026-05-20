import pandas as pd
import numpy as np
import requests
import warnings
warnings.filterwarnings("ignore")

def emit(logger, message, level="info"):
    if logger is not None:
        logger(message, level)
    else:
        print(message)

def is_date_column(col):
    return "date" in col.lower() or "time" in col.lower()

def is_money_or_quantity_column(col):
    tokens = ["amount", "price", "cost", "total", "quantity", "balance", "revenue"]
    return any(token in col.lower() for token in tokens)

def is_id_column(col):
    lowered = col.lower()
    return lowered.endswith("_id") or lowered == "id" or "transaction_id" in lowered or "customer_id" in lowered

def maybe_numeric_series(series):
    cleaned = series.astype("string").str.replace(r"[$,]", "", regex=True).str.strip()
    numeric = pd.to_numeric(cleaned, errors="coerce")
    non_null = series.notna().sum()
    if non_null == 0:
        return None, 0
    return numeric, float(numeric.notna().sum() / non_null)

class LocalRepairEngine:
    def __init__(self, model_id="llama3"):
        """
        Initializes the Repair Engine. 
        Uses a local LLM via Ollama.
        """
        self.model_id = model_id
        print(f"Configured to use local Ollama LLM ({self.model_id}) for data repair...")

    def repair_categorical_llm(self, df, logger=None):
        """
        Uses the local LLM to infer missing Merchant Categories based on Merchant Names.
        This keeps the Crux repair pass row-preserving.
        """
        emit(logger, "Scanning for missing categorical data.")
        if 'merchant_category' not in df.columns or 'merchant_name' not in df.columns:
            emit(logger, "Required columns for categorical repair ('merchant_category', 'merchant_name') are missing. Skipping.", "warning")
            return df
            
        missing_cat_mask = df['merchant_category'].isnull()
        missing_count = missing_cat_mask.sum()
        emit(logger, f"Found {missing_count} rows with missing 'merchant_category'. Initiating LLM repair.")

        for idx, row in df.loc[missing_cat_mask].iterrows():
            emit(logger, f"Analyzing row {idx + 1}: merchant_name={row.get('merchant_name', 'Unknown')}")
        
        # We process unique merchant names to save LLM calls
        unique_missing_merchants = df.loc[missing_cat_mask, 'merchant_name'].unique()
        inferred_mapping = {}
        
        for merchant in unique_missing_merchants:
            emit(logger, f"Calling Ollama {self.model_id} for merchant '{merchant}'.")
            prompt = f"You are a financial data assistant. Given a merchant name, output ONLY their category. Categories can be 'Retail', 'E-commerce', 'Entertainment', 'Transport', 'Gas Station', 'Food & Beverage'.\nMerchant: {merchant}\nCategory:"
            
            payload = {
                "model": self.model_id,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.0,
                    "num_predict": 10
                }
            }
            
            try:
                response = requests.post("http://localhost:11434/api/generate", json=payload, timeout=45)
                response.raise_for_status()
                output = response.json().get("response", "")
            except Exception as e:
                emit(logger, f"Error calling Ollama API: {e}", "error")
                output = "Unknown"
            
            # Clean up output
            category = output.strip().split('\n')[0]
            # Simple fallback if the LLM hallucinated
            valid_categories = ['Retail', 'E-commerce', 'Entertainment', 'Transport', 'Gas Station', 'Food & Beverage']
            if category not in valid_categories:
                # Basic string matching just in case
                for valid in valid_categories:
                    if valid.lower() in category.lower():
                        category = valid
                        break
                else:
                    category = "Unknown"
                    
            inferred_mapping[merchant] = category
            emit(logger, f"Repaired merchant mapping: {merchant} -> {category}")
            
        # Apply the mapping back to the dataframe
        df.loc[missing_cat_mask, 'merchant_category'] = df.loc[missing_cat_mask, 'merchant_name'].map(inferred_mapping)
        for idx, row in df.loc[missing_cat_mask].iterrows():
            emit(logger, f"Writing repair to row {idx + 1}: merchant_category={row['merchant_category']}")
        return df

    def repair_numerical_statistical(self, df, logger=None):
        """
        Repairs numerical errors using statistical rules rather than LLMs.
        e.g., negative amounts shouldn't exist in standard transactions unless they are refunds, 
        but in our dataset they are errors.
        """
        emit(logger, "Scanning for numerical anomalies.")
        if 'amount' in df.columns:
            negative_amounts = df['amount'] < 0
            neg_count = negative_amounts.sum()
            if neg_count > 0:
                emit(logger, f"Found {neg_count} rows with negative amounts. Repairing by taking absolute value.")
                for idx, row in df.loc[negative_amounts].iterrows():
                    emit(logger, f"Repairing row {idx + 1}: amount {row['amount']} -> {abs(row['amount'])}")
                df.loc[negative_amounts, 'amount'] = df.loc[negative_amounts, 'amount'].abs()

        for col in df.select_dtypes(include=[np.number]).columns:
            if is_money_or_quantity_column(col):
                negative_values = df[col] < 0
                neg_count = int(negative_values.sum())
                if neg_count > 0:
                    emit(logger, f"Found {neg_count} negative values in '{col}'. Repairing by absolute value.")
                    for idx, row in df.loc[negative_values].head(50).iterrows():
                        emit(logger, f"Repairing row {idx + 1}: {col} {row[col]} -> {abs(row[col])}")
                    df.loc[negative_values, col] = df.loc[negative_values, col].abs()
                if "quantity" in col.lower():
                    zero_values = df[col] == 0
                    if int(zero_values.sum()) > 0:
                        emit(logger, f"Found {int(zero_values.sum())} zero quantities in '{col}'. Repairing to 1.")
                        df.loc[zero_values, col] = 1
            
        # Fill missing user_ids with a placeholder or resample
        if 'user_id' in df.columns:
            missing_users = df['user_id'].isnull()
            if missing_users.sum() > 0:
                emit(logger, f"Found {missing_users.sum()} rows with missing user IDs. Repairing.")
                for idx, _ in df.loc[missing_users].iterrows():
                    emit(logger, f"Repairing row {idx + 1}: user_id -> USR_UNKNOWN")
                df.loc[missing_users, 'user_id'] = "USR_UNKNOWN"
            
        return df

    def repair_generic_business_rules(self, df, logger=None):
        emit(logger, "Running generic financial data repair rules.")

        for col in df.select_dtypes(include=["object", "string"]).columns:
            df[col] = df[col].astype("string").str.strip()
            df[col] = df[col].replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})

        for col in list(df.columns):
            if is_money_or_quantity_column(col) and (df[col].dtype == "object" or str(df[col].dtype).startswith("string")):
                numeric, ratio = maybe_numeric_series(df[col])
                if numeric is not None and ratio > 0.55:
                    emit(logger, f"Parsing numeric/currency values in '{col}' before repair.")
                    df[col] = numeric

        for col in df.columns:
            lowered = col.lower()
            if is_date_column(col):
                parsed = pd.to_datetime(df[col], errors="coerce")
                invalid_count = int(parsed.isna().sum())
                fallback = parsed.dropna().mode()
                fallback_value = fallback.iloc[0] if not fallback.empty else pd.Timestamp.today().normalize()
                if invalid_count:
                    emit(logger, f"Repairing {invalid_count} invalid dates in '{col}' with {fallback_value.date()}.")
                df[col] = parsed.fillna(fallback_value).dt.strftime("%Y-%m-%d")

            if is_id_column(col) and df[col].isnull().any():
                prefix = "ID"
                if "transaction" in lowered:
                    prefix = "TXN"
                elif "customer" in lowered:
                    prefix = "CUST"
                missing_count = int(df[col].isnull().sum())
                emit(logger, f"Repairing {missing_count} missing IDs in '{col}'.")
                df[col] = [f"{prefix}_REPAIRED_{idx + 1}" if pd.isna(value) else value for idx, value in df[col].items()]

            if "product" in lowered and "name" in lowered:
                product_prefixes = {
                    "c": "Coffee",
                    "co": "Coffee",
                    "cof": "Coffee",
                    "coff": "Coffee",
                    "coffe": "Coffee",
                    "coffee": "Coffee",
                    "coffee m": "Coffee Machine",
                    "coffee ma": "Coffee Machine",
                    "coffee mac": "Coffee Machine",
                    "coffee mach": "Coffee Machine",
                    "coffee machi": "Coffee Machine",
                    "coffee machin": "Coffee Machine",
                    "coffee machine": "Coffee Machine",
                    "h": "Headphones",
                    "he": "Headphones",
                    "hea": "Headphones",
                    "head": "Headphones",
                    "headp": "Headphones",
                    "headph": "Headphones",
                    "headpho": "Headphones",
                    "headphon": "Headphones",
                    "headphone": "Headphones",
                    "headphones": "Headphones",
                    "l": "Laptop",
                    "la": "Laptop",
                    "lap": "Laptop",
                    "lapt": "Laptop",
                    "lapto": "Laptop",
                    "laptop": "Laptop",
                    "s": "Smartphone",
                    "sm": "Smartphone",
                    "sma": "Smartphone",
                    "smar": "Smartphone",
                    "smart": "Smartphone",
                    "smartp": "Smartphone",
                    "smartph": "Smartphone",
                    "smartpho": "Smartphone",
                    "smartphon": "Smartphone",
                    "smartphone": "Smartphone",
                    "t": "Tablet",
                    "ta": "Tablet",
                    "tab": "Tablet",
                    "tabl": "Tablet",
                    "table": "Tablet",
                    "tablet": "Tablet",
                }
                normalized = df[col].astype("string").str.strip()
                repaired = normalized.str.lower().map(product_prefixes).fillna(normalized)
                changed_count = int((normalized != repaired).sum())
                if changed_count:
                    emit(logger, f"Repairing {changed_count} partial product names in '{col}' using known product vocabulary.")
                df[col] = repaired

            if "payment" in lowered and "method" in lowered:
                mapping = {
                    "creditcard": "Credit Card",
                    "credit card": "Credit Card",
                    "pay pal": "PayPal",
                    "paypal": "PayPal",
                    "cash": "Cash"
                }
                emit(logger, f"Normalizing payment method values in '{col}'.")
                df[col] = df[col].astype("string").str.strip().str.lower().map(mapping).fillna(df[col])

            if "status" in lowered:
                emit(logger, f"Normalizing transaction status values in '{col}'.")
                status_mapping = {
                    "complete": "Completed",
                    "completed": "Completed",
                    "pending": "Pending",
                    "failed": "Failed",
                    "needs review": "Needs Review",
                }
                normalized_status = df[col].astype("string").str.strip().str.lower()
                df[col] = normalized_status.map(status_mapping).fillna(df[col])
                df[col] = df[col].astype("string").replace({"Nan": "Needs Review", "None": "Needs Review", "<NA>": "Needs Review"})
                df[col] = df[col].fillna("Needs Review")

        for col in df.select_dtypes(include=[np.number]).columns:
            if df[col].isnull().any():
                median = df[col].median()
                if pd.isna(median):
                    median = 0
                emit(logger, f"Repairing numeric blanks in '{col}' with median {median}.")
                df[col] = df[col].fillna(median)

        for col in df.select_dtypes(include=["object", "string"]).columns:
            if df[col].isnull().any():
                emit(logger, f"Repairing text blanks in '{col}' with Needs Review.")
                df[col] = df[col].fillna("Needs Review")

        return df

    def run_repair_pipeline(self, input_csv, output_csv, logger=None):
        emit(logger, "--- Starting Data Repair Engine ---")
        emit(logger, f"Loading source CSV: {input_csv}")
        df = pd.read_csv(input_csv)
        
        initial_nulls = df.isnull().sum().sum()
        emit(logger, f"Initial null values: {initial_nulls}")
        duplicate_count = int(df.duplicated().sum())
        if duplicate_count:
            emit(logger, f"Found {duplicate_count} duplicate rows. Removing duplicates before repair.")
            df = df.drop_duplicates()
        
        for idx, row in df.head(200).iterrows():
            row_id = row.get("transaction_id", row.get("Transaction_ID", idx + 1))
            emit(logger, f"Inspecting row {idx + 1}: {row_id}")
        if len(df) > 200:
            emit(logger, f"Skipped detailed row logging for remaining {len(df) - 200} rows to keep the UI responsive.")
        
        df = self.repair_generic_business_rules(df, logger=logger)
        df = self.repair_numerical_statistical(df, logger=logger)
        df = self.repair_categorical_llm(df, logger=logger)
        
        final_nulls = df.isnull().sum().sum()
        emit(logger, f"Final null values: {final_nulls}")
        
        df.to_csv(output_csv, index=False)
        emit(logger, f"Repaired dataset saved to {output_csv}")
        return df

if __name__ == "__main__":
    engine = LocalRepairEngine()
    engine.run_repair_pipeline("data/raw_transactions.csv", "data/repaired_transactions.csv")
