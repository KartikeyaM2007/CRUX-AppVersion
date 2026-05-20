import pandas as pd
import numpy as np
from scipy.stats import ks_2samp

class LocalEvaluationEngine:
    def __init__(self):
        pass

    def evaluate_synthetic_data(self, real_csv, synthetic_csv):
        """
        Evaluates the Fidelity of the synthetic data against the repaired real data.
        Uses Kolmogorov-Smirnov (KS) test for numerical columns.
        """
        print(f"\n--- Starting Evaluation Engine ---")
        real_df = pd.read_csv(real_csv)
        synth_df = pd.read_csv(synthetic_csv)
        
        print("1. Structural Validation:")
        print(f"  Real shape: {real_df.shape}")
        print(f"  Synthetic shape: {synth_df.shape}")
        
        # Evaluate numerical distributions
        print("\n2. Numerical Distribution Fidelity (KS Test):")
        # Null hypothesis: Both samples are drawn from the same distribution.
        # Higher p-value (> 0.05) means we cannot reject the null hypothesis (i.e., they are similar).
        num_cols = real_df.select_dtypes(include=[np.number]).columns
        
        results = {
            "numerical": [],
            "categorical": []
        }
        
        for col in num_cols:
            stat, p_value = ks_2samp(real_df[col], synth_df[col])
            status = "PASS" if p_value > 0.05 else "FAIL"
            print(f"  - {col}: KS Stat={stat:.4f}, p-value={p_value:.4f} -> {status}")
            results["numerical"].append({
                "column": col,
                "ks_stat": round(stat, 4),
                "p_value": round(p_value, 4),
                "status": status
            })
            
        # Evaluate categorical distributions (top value frequency) for shared low-cardinality text columns.
        print("\n3. Categorical Distribution Fidelity (Top Class Frequency):")
        cat_cols = []
        for col in real_df.columns:
            if col not in synth_df.columns:
                continue
            if real_df[col].dtype == object or str(real_df[col].dtype).startswith("string"):
                unique_count = real_df[col].nunique(dropna=True)
                if 1 < unique_count <= 50:
                    cat_cols.append(col)
        for col in cat_cols:
            real_counts = real_df[col].value_counts(normalize=True)
            synth_counts = synth_df[col].value_counts(normalize=True)
            if not real_counts.empty and not synth_counts.empty:
                real_freq = real_counts.iloc[0]
                synth_freq = synth_counts.iloc[0]
                diff = abs(real_freq - synth_freq)
                print(f"  - {col}: Top Class Freq (Real={real_freq:.2f}, Synth={synth_freq:.2f}), Diff={diff:.4f}")
                results["categorical"].append({
                    "column": col,
                    "real_freq": round(real_freq, 2),
                    "synth_freq": round(synth_freq, 2),
                    "diff": round(diff, 4)
                })
            
        print("\nEvaluation Complete.")
        return results


if __name__ == "__main__":
    engine = LocalEvaluationEngine()
    engine.evaluate_synthetic_data("repaired_transactions.csv", "synthetic_transactions.csv")
