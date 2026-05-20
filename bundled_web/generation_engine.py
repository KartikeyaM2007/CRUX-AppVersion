import pandas as pd
import numpy as np
from ctgan import CTGAN
import time
import sys


if getattr(sys, "frozen", False):
    from ctgan.data_transformer import DataTransformer

    DataTransformer._parallel_transform = DataTransformer._synchronous_transform

def emit(logger, message, level="info"):
    if logger is not None:
        logger(message, level)
    else:
        print(message)

def is_id_column(col):
    lowered = str(col).lower()
    return lowered.endswith("_id") or lowered == "id" or "transaction_id" in lowered or "customer_id" in lowered

def is_date_column(col):
    lowered = str(col).lower()
    return "date" in lowered or "time" in lowered

class LocalGenerationEngine:
    def __init__(self):
        """
        Initializes the Tabular Data Generation Engine using CTGAN.
        CTGAN is highly optimized for tabular data and runs very well on 
        consumer GPUs (RTX 3050).
        """
        self.model = CTGAN(epochs=25, verbose=False)
        self.original_columns = []
        self.id_columns = []
        self.date_columns = []
        self.date_ranges = {}
        self.id_prefixes = {}
        self.numeric_references = {}
        self.binary_references = {}

    def train_generator(self, input_csv, discrete_columns, logger=None):
        """
        Trains the CTGAN on the repaired, clean seed dataset.
        """
        emit(logger, "--- Starting Data Generation Engine ---")
        emit(logger, f"Loading data from {input_csv}.")
        df = pd.read_csv(input_csv)
        df.columns = [str(col) for col in df.columns]
        self.original_columns = list(df.columns)
        self.id_columns = [col for col in df.columns if is_id_column(col)]
        self.date_columns = [col for col in df.columns if is_date_column(col)]
        modeling_drop_cols = self.id_columns + self.date_columns
        train_source_df = df.drop(columns=modeling_drop_cols, errors="ignore")
        train_source_df.columns = [str(col) for col in train_source_df.columns]
        self.numeric_references = {}
        for col in train_source_df.select_dtypes(include=[np.number]).columns:
            reference = pd.to_numeric(train_source_df[col], errors="coerce").dropna().to_numpy()
            if len(reference):
                self.numeric_references[col] = np.sort(reference)
                unique_values = sorted(pd.Series(reference).dropna().unique().tolist())
                if len(unique_values) == 2 and set(unique_values).issubset({0, 1, 0.0, 1.0}):
                    positive_rate = float((reference == 1).mean())
                    self.binary_references[col] = {
                        "positive_rate": positive_rate,
                        "dtype": str(train_source_df[col].dtype)
                    }
        discrete_columns = [
            str(col) for col in discrete_columns
            if str(col) in train_source_df.columns
        ]
        self.date_ranges = {}
        for col in self.date_columns:
            parsed = pd.to_datetime(df[col], errors="coerce").dropna()
            if parsed.empty:
                self.date_ranges[col] = (pd.Timestamp.today().normalize(), pd.Timestamp.today().normalize())
            else:
                self.date_ranges[col] = (parsed.min().normalize(), parsed.max().normalize())
        self.id_prefixes = {}
        for col in self.id_columns:
            sample = df[col].dropna().astype(str).head(1)
            value = sample.iloc[0] if not sample.empty else col
            prefix = "".join(ch for ch in value if not ch.isdigit()).strip("_- ")
            if not prefix:
                prefix = "ID"
            self.id_prefixes[col] = prefix
        emit(logger, f"Training source has {len(df)} rows and {len(df.columns)} columns.")
        if modeling_drop_cols:
            emit(logger, f"Regenerating identity/date columns outside CTGAN: {', '.join(modeling_drop_cols)}.")
        for idx, row in df.head(200).iterrows():
            row_id = row.get("transaction_id", idx + 1)
            emit(logger, f"Analyzing training row {idx + 1}: {row_id}")
        if len(df) > 200:
            emit(logger, f"Skipped detailed row logging for remaining {len(df) - 200} rows to keep the UI responsive.")
        train_df = train_source_df
        max_train_rows = 10000
        if len(train_source_df) > max_train_rows:
            train_df = train_source_df.sample(max_train_rows, random_state=42).reset_index(drop=True)
            emit(logger, f"Training sample capped at {max_train_rows} rows from {len(df)} source rows for local runtime.")
        
        # Ensure date is treated as a string or handle it properly
        # For simplicity in the prototype, we treat date as a categorical/discrete column 
        # or we could drop it and regenerate it. Let's keep it discrete for now.
        
        emit(logger, "Training CTGAN model. This will use available local acceleration if supported.")
        start_time = time.time()
        
        # Train the model
        self.model.fit(train_df, discrete_columns)
        
        end_time = time.time()
        duration = end_time - start_time
        emit(logger, f"Training completed in {duration:.2f} seconds.")
        return {
            "duration_seconds": round(duration, 2),
            "training_rows": int(len(train_df)),
            "source_rows": int(len(df)),
            "discrete_columns": discrete_columns,
            "regenerated_columns": modeling_drop_cols
        }
        
    def generate_synthetic_data(self, num_rows=1000, output_csv="synthetic_transactions.csv", logger=None):
        """
        Generates net-new synthetic rows sampled from the learned distribution.
        """
        emit(logger, f"Generating {num_rows} synthetic rows.")
        synthetic_data = self.model.sample(num_rows)
        synthetic_data = synthetic_data.reset_index(drop=True)
        rng = np.random.default_rng(42)
        for col, reference in self.binary_references.items():
            if col not in synthetic_data.columns:
                continue
            positive_rate = float(reference.get("positive_rate", 0.0))
            positives = int(round(num_rows * positive_rate))
            if positive_rate > 0 and positives == 0:
                positives = 1
            values = np.zeros(num_rows, dtype=int)
            if positives > 0:
                selected = rng.choice(num_rows, size=min(positives, num_rows), replace=False)
                values[selected] = 1
            synthetic_data[col] = values
            emit(logger, f"Calibrated rare-event/binary column '{col}' to source positive rate {positive_rate:.2%}.")
        for col, reference in self.numeric_references.items():
            if col not in synthetic_data.columns or len(reference) == 0:
                continue
            if col in self.binary_references:
                continue
            synthetic_numeric = pd.to_numeric(synthetic_data[col], errors="coerce")
            if synthetic_numeric.notna().sum() == 0:
                continue
            ranks = synthetic_numeric.rank(method="average", pct=True).fillna(0.5).to_numpy()
            calibrated = np.quantile(reference, ranks)
            synthetic_data[col] = calibrated
            emit(logger, f"Calibrated generated numeric distribution for '{col}' against repaired source data.")
        if "amount" in synthetic_data.columns:
            negative_amounts = synthetic_data["amount"] < 0
            negative_count = int(negative_amounts.sum())
            emit(logger, f"Post-generation amount validation found {negative_count} negative values.")
            if negative_count > 0:
                for idx, row in synthetic_data.loc[negative_amounts].iterrows():
                    emit(logger, f"Correcting synthetic row {idx + 1}: amount {row['amount']} -> {abs(row['amount'])}")
                synthetic_data.loc[negative_amounts, "amount"] = synthetic_data.loc[negative_amounts, "amount"].abs()
        for col in synthetic_data.select_dtypes(include=[np.number]).columns:
            if any(token in col.lower() for token in ["amount", "price", "cost", "total", "quantity", "balance"]):
                negative_values = synthetic_data[col] < 0
                negative_count = int(negative_values.sum())
                if negative_count:
                    emit(logger, f"Post-generation validation found {negative_count} negative values in '{col}'. Correcting to absolute values.")
                    synthetic_data.loc[negative_values, col] = synthetic_data.loc[negative_values, col].abs()
            if "quantity" in col.lower():
                synthetic_data[col] = synthetic_data[col].round().clip(lower=1)
        for col in self.id_columns:
            prefix = self.id_prefixes.get(col, "ID")
            synthetic_data[col] = [f"{prefix}_SYN_{idx + 1:06d}" for idx in range(num_rows)]
        for col in self.date_columns:
            start, end = self.date_ranges.get(col, (pd.Timestamp.today().normalize(), pd.Timestamp.today().normalize()))
            span = max(int((end - start).days), 0)
            offsets = rng.integers(0, span + 1, size=num_rows) if span else np.zeros(num_rows, dtype=int)
            synthetic_data[col] = [(start + pd.Timedelta(days=int(offset))).strftime("%Y-%m-%d") for offset in offsets]
        if self.original_columns:
            for col in self.original_columns:
                if col not in synthetic_data.columns:
                    synthetic_data[col] = ""
            synthetic_data = synthetic_data[self.original_columns]
        for idx, row in synthetic_data.head(200).iterrows():
            row_id = row.get("transaction_id", idx + 1)
            emit(logger, f"Creating row {idx + 1}: synthetic transaction {row_id}")
        if len(synthetic_data) > 200:
            emit(logger, f"Generated {len(synthetic_data) - 200} additional rows without detailed row logging.")
        
        synthetic_data.to_csv(output_csv, index=False)
        emit(logger, f"Synthetic dataset saved to {output_csv}")
        
        # Quick sanity check on generated data
        emit(logger, "Sample generated data preview is ready.")
        return synthetic_data

if __name__ == "__main__":
    engine = LocalGenerationEngine()
    
    discrete_cols = [
        'transaction_id', 
        'date', 
        'user_id', 
        'merchant_name', 
        'merchant_category', 
        'is_fraud'
    ]
    
    engine.train_generator("data/repaired_transactions.csv", discrete_cols)
    engine.generate_synthetic_data(1000, "data/synthetic_transactions.csv")
