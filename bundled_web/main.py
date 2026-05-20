import os
from mock_data_generator import generate_mock_financial_data
from repair_engine import LocalRepairEngine
from generation_engine import LocalGenerationEngine
from evaluation_engine import LocalEvaluationEngine

def main():
    print("==================================================")
    print("   SYNTHETIC DATA INFRASTRUCTURE - LOCAL ENGINE   ")
    print("==================================================\n")
    
    raw_csv = "data/raw_transactions.csv"
    repaired_csv = "data/repaired_transactions.csv"
    synthetic_csv = "data/synthetic_transactions.csv"
    
    # 1. Generate dirty mock data (simulate client upload)
    print("STEP 1: Ingesting Client Data")
    generate_mock_financial_data(num_rows=2000, output_path=raw_csv)
    
    # 2. Repair Data using Local LLM & Stats
    print("\nSTEP 2: Data Repair & Cleaning")
    # For testing on a 4GB VRAM GPU, we use a tiny 0.5B model.
    # It will automatically download the first time it's run.
    repair_engine = LocalRepairEngine(model_id="Qwen/Qwen2.5-0.5B-Instruct")
    repair_engine.run_repair_pipeline(raw_csv, repaired_csv)
    
    # 3. Train CTGAN & Generate Synthetic Data
    print("\nSTEP 3: Synthetic Data Generation")
    gen_engine = LocalGenerationEngine()
    
    discrete_cols = [
        'transaction_id', 
        'date', 
        'user_id', 
        'merchant_name', 
        'merchant_category', 
        'is_fraud'
    ]
    
    gen_engine.train_generator(repaired_csv, discrete_cols)
    gen_engine.generate_synthetic_data(num_rows=2000, output_csv=synthetic_csv)
    
    # 4. Evaluate
    print("\nSTEP 4: Evaluation & Validation")
    eval_engine = LocalEvaluationEngine()
    eval_engine.evaluate_synthetic_data(repaired_csv, synthetic_csv)
    
    print("\n==================================================")
    print(" PIPELINE COMPLETE. SYNTHETIC DATA READY FOR USE.")
    print("==================================================")

if __name__ == "__main__":
    main()
