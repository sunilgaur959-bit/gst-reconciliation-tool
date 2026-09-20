import os
import time
import re
import pandas as pd
from flask import Flask, render_template, request, send_file, flash, redirect, url_for
from werkzeug.utils import secure_filename
import io

app = Flask(__name__)
app.secret_key = "supersecretkey"

# Configuration
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'downloads'
ALLOWED_EXTENSIONS = {'xlsx', 'xls'}

# Ensure directories exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ==============================
# RECONCILIATION LOGIC
# ==============================

def read_sheet_safely(file_path, sheet):
    # Determine engine based on extension
    engine = 'openpyxl' if file_path.endswith('.xlsx') else 'xlrd'
    
    try:
        # Read only the first 50 rows to detect the header location quickly without memory bloat
        raw = pd.read_excel(file_path, sheet_name=sheet, header=None, nrows=50, engine=engine)
    except ValueError:
       # Sheet not found
       raise Exception(f"Sheet '{sheet}' not found in the uploaded file.")

    header_row = None
    # Look for header row in the first rows
    for i in range(len(raw)):
        row_values = raw.iloc[i].astype(str).tolist()
        row_text = " ".join(row_values).lower()
        # Heuristic to find header
        if ("supplier" in row_text or "party" in row_text) and ("gst" in row_text or "invoice" in row_text):
            header_row = i
            break
        # Fallback if generic terms found
        if "supplier" in row_text or "party" in row_text:
             header_row = i
             break

    if header_row is None:
        # If strictly "supplier" or "party" not found, try finding "Invoice"
        for i in range(len(raw)):
             row_text = " ".join(raw.iloc[i].astype(str)).lower()
             if "invoice" in row_text and ("date" in row_text or "no" in row_text):
                 header_row = i
                 break
    
    if header_row is None:
        # Default to 0 if all else fails
        header_row = 0

    # Read the full dataset with all entries starting from the header row
    return pd.read_excel(file_path, sheet_name=sheet, header=header_row, engine=engine)

def normalise_columns(df):
    df.columns = (
        df.columns.astype(str)
        .str.strip()
        .str.replace("\u00a0", "", regex=True)
        .str.replace("\n", "", regex=True)
        .str.replace("\r", "", regex=True)
    )
    return df

def map_columns(df):
    mapping = {
        "Supplier Name": "Supplier_Name",
        "Party Name": "Supplier_Name",
        "Vendor Name": "Supplier_Name",
        "Name of the Supplier": "Supplier_Name",

        "Invoice No": "Invoice_No",
        "Invoice Number": "Invoice_No",
        "Bill No": "Invoice_No",
        "Document Number": "Invoice_No",

        "Integrated Tax": "IGST",
        "Central Tax": "CGST",
        "State Tax": "SGST",
        "IGST Amount": "IGST",
        "CGST Amount": "CGST",
        "SGST Amount": "SGST",
        
        "GSTIN": "GSTIN",
        "GSTIN of Supplier": "GSTIN",
        "Supplier GSTIN": "GSTIN",
        "GST Number": "GSTIN",
    }
    # Case insensitive mapping attempt
    new_cols = {}
    for col in df.columns:
        for k, v in mapping.items():
            if k.lower() == col.lower():
                new_cols[col] = v
                break
    df.rename(columns=new_cols, inplace=True)
    return df

def clean_supplier(x):
    if pd.isna(x):
        return ""
    return (
        str(x).upper()
        .replace("PVT", "")
        .replace("LTD", "")
        .replace("LIMITED", "")
        .replace("LLP", "")
        .replace(".", "")
        .strip()
    )

def clean_invoice(x):
    if pd.isna(x):
        return ""
    # Remove non-alphanumeric except maybe / or - if needed, but original script removed everything
    return re.sub(r"[^A-Z0-9]", "", str(x).upper())

def clean_gstin(x):
    if pd.isna(x):
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(x).upper().strip())

def tax_structure(r):
    # Ensure columns exist, default to 0 if not
    igst = r.get("IGST", 0)
    cgst = r.get("CGST", 0)
    sgst = r.get("SGST", 0)
    
    if igst > 0 and cgst == 0 and sgst == 0:
        return "IGST"
    if igst == 0 and cgst > 0 and sgst > 0:
        return "CGST_SGST"
    return "OTHER"

def process_reconciliation(input_path, output_path):
    TOLERANCE = 1
    import math
    # Consistent rounding: always round .5 UP (avoids Python's banker's rounding
    # which can differ across versions and cause hash bucket mismatches)
    def iround(v):
        return int(math.floor(float(v) + 0.5))

    try:
        # 1. Read Sheets
        gstr2b = read_sheet_safely(input_path, "GSTR_2B")
        books = read_sheet_safely(input_path, "BOOKS")

        # 2. Normalise & Map
        gstr2b = map_columns(normalise_columns(gstr2b))
        books = map_columns(normalise_columns(books))

        # 3. Clean Data
        for df in [gstr2b, books]:
            if "Invoice_No" not in df.columns:
                df["Invoice_No"] = ""
            if "Supplier_Name" not in df.columns:
                 df["Supplier_Name"] = "" # Handle missing supplier name column
            if "GSTIN" not in df.columns:
                 df["GSTIN"] = ""
                 
            # Ensure regex columns are present
            for col in ["IGST", "CGST", "SGST"]:
                if col not in df.columns:
                    df[col] = 0

            df["Invoice_No"] = df["Invoice_No"].astype(str)
            df["Invoice_No_CLEAN"] = df["Invoice_No"].apply(clean_invoice)
            df["Supplier_Name_CLEAN"] = df["Supplier_Name"].apply(clean_supplier)
            df["GSTIN_CLEAN"] = df["GSTIN"].apply(clean_gstin)

            for col in ["IGST", "CGST", "SGST"]:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

            df["RECO_REMARK"] = "NOT MATCHED"
            df["USED"] = False
        
        # 4. Tax Structure (Vectorized with numpy for near-instant execution)
        import numpy as np
        def compute_tax_structure(df):
            igst = df["IGST"]
            cgst = df["CGST"]
            sgst = df["SGST"]
            cond_igst = (igst > 0) & (cgst == 0) & (sgst == 0)
            cond_cgst_sgst = (igst == 0) & (cgst > 0) & (sgst > 0)
            return np.select([cond_igst, cond_cgst_sgst], ["IGST", "CGST_SGST"], default="OTHER")

        gstr2b["TAX_STRUCTURE"] = compute_tax_structure(gstr2b)
        books["TAX_STRUCTURE"] = compute_tax_structure(books)

        # 5A. Invoice Number Match (GSTIN + Invoice Number + Tax Structure)
        from collections import defaultdict
        
        gstr2b_idx = defaultdict(list)
        for row in gstr2b.itertuples():
            inv_c = getattr(row, "Invoice_No_CLEAN", "")
            gst_c = getattr(row, "GSTIN_CLEAN", "")
            tax_s = getattr(row, "TAX_STRUCTURE", "")
            if inv_c != "" and gst_c != "":
                gstr2b_idx[(gst_c, inv_c, tax_s)].append(row.Index)
            elif inv_c != "":
                gstr2b_idx[("", inv_c, tax_s)].append(row.Index)

        used_gstr2b = set()
        used_books = set()

        matched_books_indices = []
        matched_gstr2b_indices = []

        gstr2b_igst = gstr2b["IGST"].to_dict()
        gstr2b_cgst = gstr2b["CGST"].to_dict()
        gstr2b_sgst = gstr2b["SGST"].to_dict()

        valid_books = books[books["Invoice_No_CLEAN"] != ""]
        if not valid_books.empty:
            books_grouped = valid_books.groupby(["GSTIN_CLEAN", "Invoice_No_CLEAN"])
            books_agg = books_grouped.agg({
                "IGST": "sum",
                "CGST": "sum",
                "SGST": "sum",
                "TAX_STRUCTURE": "first"
            })
            books_group_indices = books_grouped.indices

            for (gst_c, inv_c), row_agg in books_agg.iterrows():
                tax_struct = row_agg["TAX_STRUCTURE"]
                candidates = [j for j in gstr2b_idx.get((gst_c, inv_c, tax_struct), []) if j not in used_gstr2b]
                if not candidates and gst_c == "":
                    candidates = [j for j in gstr2b_idx.get(("", inv_c, tax_struct), []) if j not in used_gstr2b]
                if not candidates:
                    continue

                ig_s = row_agg["IGST"]
                cg_s = row_agg["CGST"]
                sg_s = row_agg["SGST"]

                for j in candidates:
                    if (
                        abs(gstr2b_igst[j] - ig_s) <= TOLERANCE and
                        abs(gstr2b_cgst[j] - cg_s) <= TOLERANCE and
                        abs(gstr2b_sgst[j] - sg_s) <= TOLERANCE
                    ):
                        grp = list(books_group_indices[(gst_c, inv_c)])
                        matched_books_indices.extend(grp)
                        matched_gstr2b_indices.append(j)
                        used_books.update(grp)
                        used_gstr2b.add(j)
                        break

        # 5B. Fallback Match: Within the SAME Supplier (GSTIN) by Tax Amount
        gstr2b_gstin_tax_buckets = defaultdict(list)
        for row in gstr2b.itertuples():
            if row.Index not in used_gstr2b:
                gst_c = getattr(row, "GSTIN_CLEAN", "")
                if gst_c != "":
                    key = (
                        gst_c,
                        getattr(row, "TAX_STRUCTURE", ""),
                        iround(gstr2b_igst[row.Index]),
                        iround(gstr2b_cgst[row.Index]),
                        iround(gstr2b_sgst[row.Index])
                    )
                    gstr2b_gstin_tax_buckets[key].append(row.Index)

        books_igst = books["IGST"].to_dict()
        books_cgst = books["CGST"].to_dict()
        books_sgst = books["SGST"].to_dict()
        books_tax = books["TAX_STRUCTURE"].to_dict()
        books_gstin = books["GSTIN_CLEAN"].to_dict()

        for b_idx in books.index:
            if b_idx in used_books:
                continue
            gst_c = books_gstin.get(b_idx, "")
            if not gst_c:
                continue

            tax_struct = books_tax.get(b_idx, "")
            ig_val = books_igst.get(b_idx, 0)
            cg_val = books_cgst.get(b_idx, 0)
            sg_val = books_sgst.get(b_idx, 0)

            round_ig = iround(ig_val)
            round_cg = iround(cg_val)
            round_sg = iround(sg_val)

            found = False
            for d_i in (0, -1, 1):
                for d_c in (0, -1, 1):
                    for d_s in (0, -1, 1):
                        search_key = (gst_c, tax_struct, round_ig + d_i, round_cg + d_c, round_sg + d_s)
                        candidates = gstr2b_gstin_tax_buckets.get(search_key)
                        if not candidates:
                            continue
                        for j in candidates:
                            if j in used_gstr2b:
                                continue
                            if (
                                abs(gstr2b_igst[j] - ig_val) <= TOLERANCE and
                                abs(gstr2b_cgst[j] - cg_val) <= TOLERANCE and
                                abs(gstr2b_sgst[j] - sg_val) <= TOLERANCE
                            ):
                                matched_books_indices.append(b_idx)
                                matched_gstr2b_indices.append(j)
                                used_books.add(b_idx)
                                used_gstr2b.add(j)
                                found = True
                                break
                        if found:
                            break
                    if found:
                        break
                if found:
                    break

        # Apply bulk updates instantly without row-by-row memory fragmentation
        if matched_books_indices:
            books.loc[matched_books_indices, "RECO_REMARK"] = "MATCHED"
            books.loc[matched_books_indices, "USED"] = True
        
        if matched_gstr2b_indices:
            gstr2b.loc[matched_gstr2b_indices, "RECO_REMARK"] = "MATCHED"
            gstr2b.loc[matched_gstr2b_indices, "USED"] = True

        # 6. Write Output
        drop_cols = ["Invoice_No_CLEAN", "Supplier_Name_CLEAN", "GSTIN_CLEAN", "TAX_STRUCTURE", "USED"]
        # Ensure GSTIN is kept (it's not in drop_cols, so it should be fine).
        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            gstr2b.drop(columns=drop_cols, errors="ignore").to_excel(writer, sheet_name="GSTR_2B", index=False)
            books.drop(columns=drop_cols, errors="ignore").to_excel(writer, sheet_name="BOOKS", index=False)
        
        return None # Success
    except Exception as e:
        import traceback
        return f"Error details: {str(e)}"

# ==============================
# ROUTES
# ==============================

@app.errorhandler(500)
def internal_server_error(e):
    return "A very deep server crash occurred. Please check if your file is too large for the cloud's memory.", 500

@app.errorhandler(Exception)
def handle_exception(e):
    import traceback
    return f"CRITICAL CRASH TRACE:\n{traceback.format_exc()}", 500

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)
        
        file = request.files['file']
        if file.filename == '':
            flash('No selected file')
            return redirect(request.url)
            
        if file and allowed_file(file.filename):
            import uuid
            unique_id = str(uuid.uuid4())[:8]
            filename = f"{unique_id}_{secure_filename(file.filename)}"
            input_path = os.path.join(UPLOAD_FOLDER, filename)
            output_filename = f"Reconciled_{filename}"
            output_path = os.path.join(OUTPUT_FOLDER, output_filename)
            
            file.save(input_path)
            
            # Process
            error = process_reconciliation(input_path, output_path)
            
            if error:
                return f"Processing Error:\n{error}", 500
            
            
            return send_file(output_path, as_attachment=True)
            
    return render_template('index.html')

@app.route('/version')
def version():
    import sys, numpy as np
    return {
        "status": "online",
        "version": "v6.0-diagnose",
        "python": sys.version,
        "pandas": pd.__version__,
        "numpy": np.__version__,
    }

@app.route('/diagnose', methods=['POST'])
def diagnose():
    """Diagnostic endpoint: upload a file and get JSON match diagnostics."""
    import sys, numpy as np, json
    from collections import defaultdict

    diag = {
        "python": sys.version,
        "pandas": pd.__version__,
        "numpy": np.__version__,
    }

    try:
        if 'file' not in request.files:
            return {"error": "no file"}, 400
        file = request.files['file']
        if not file.filename:
            return {"error": "empty filename"}, 400

        # Save temp
        import uuid
        unique_id = str(uuid.uuid4())[:8]
        filename = f"{unique_id}_{secure_filename(file.filename)}"
        input_path = os.path.join(UPLOAD_FOLDER, filename)
        file.save(input_path)

        # Read
        gstr2b = read_sheet_safely(input_path, "GSTR_2B")
        books = read_sheet_safely(input_path, "BOOKS")
        gstr2b = map_columns(normalise_columns(gstr2b))
        books = map_columns(normalise_columns(books))

        diag["gstr2b_rows"] = len(gstr2b)
        diag["books_rows"] = len(books)
        diag["gstr2b_cols"] = list(gstr2b.columns)
        diag["books_cols"] = list(books.columns)

        TOLERANCE = 1

        # Clean
        for df in [gstr2b, books]:
            if "Invoice_No" not in df.columns:
                df["Invoice_No"] = ""
            if "Supplier_Name" not in df.columns:
                df["Supplier_Name"] = ""
            if "GSTIN" not in df.columns:
                df["GSTIN"] = ""
            for col in ["IGST", "CGST", "SGST"]:
                if col not in df.columns:
                    df[col] = 0
            df["Invoice_No"] = df["Invoice_No"].astype(str)
            df["Invoice_No_CLEAN"] = df["Invoice_No"].apply(clean_invoice)
            df["Supplier_Name_CLEAN"] = df["Supplier_Name"].apply(clean_supplier)
            df["GSTIN_CLEAN"] = df["GSTIN"].apply(clean_gstin)
            for col in ["IGST", "CGST", "SGST"]:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
            df["RECO_REMARK"] = "NOT MATCHED"
            df["USED"] = False

        # Sample GSTIN_CLEAN
        diag["books_gstin_clean_sample"] = books["GSTIN_CLEAN"].head(10).tolist()
        diag["gstr2b_gstin_clean_sample"] = gstr2b["GSTIN_CLEAN"].head(10).tolist()
        diag["books_gstin_clean_empty_count"] = int((books["GSTIN_CLEAN"] == "").sum())
        diag["gstr2b_gstin_clean_empty_count"] = int((gstr2b["GSTIN_CLEAN"] == "").sum())
        diag["books_gstin_clean_nunique"] = int(books["GSTIN_CLEAN"].nunique())

        # Tax structure
        def compute_tax_structure(df):
            igst = df["IGST"]
            cgst = df["CGST"]
            sgst = df["SGST"]
            cond_igst = (igst > 0) & (cgst == 0) & (sgst == 0)
            cond_cgst_sgst = (igst == 0) & (cgst > 0) & (sgst > 0)
            return np.select([cond_igst, cond_cgst_sgst], ["IGST", "CGST_SGST"], default="OTHER")

        gstr2b["TAX_STRUCTURE"] = compute_tax_structure(gstr2b)
        books["TAX_STRUCTURE"] = compute_tax_structure(books)

        # Step 5A
        gstr2b_idx = defaultdict(list)
        for row in gstr2b.itertuples():
            inv_c = getattr(row, "Invoice_No_CLEAN", "")
            gst_c = getattr(row, "GSTIN_CLEAN", "")
            tax_s = getattr(row, "TAX_STRUCTURE", "")
            if inv_c != "" and gst_c != "":
                gstr2b_idx[(gst_c, inv_c, tax_s)].append(row.Index)
            elif inv_c != "":
                gstr2b_idx[("", inv_c, tax_s)].append(row.Index)

        used_gstr2b = set()
        used_books = set()
        matched_books_indices = []
        matched_gstr2b_indices = []

        gstr2b_igst = gstr2b["IGST"].to_dict()
        gstr2b_cgst = gstr2b["CGST"].to_dict()
        gstr2b_sgst = gstr2b["SGST"].to_dict()

        valid_books = books[books["Invoice_No_CLEAN"] != ""]
        if not valid_books.empty:
            books_grouped = valid_books.groupby(["GSTIN_CLEAN", "Invoice_No_CLEAN"])
            books_agg = books_grouped.agg({
                "IGST": "sum",
                "CGST": "sum",
                "SGST": "sum",
                "TAX_STRUCTURE": "first"
            })
            books_group_indices = books_grouped.indices

            for (gst_c, inv_c), row_agg in books_agg.iterrows():
                tax_struct = row_agg["TAX_STRUCTURE"]
                candidates = [j for j in gstr2b_idx.get((gst_c, inv_c, tax_struct), []) if j not in used_gstr2b]
                if not candidates and gst_c == "":
                    candidates = [j for j in gstr2b_idx.get(("", inv_c, tax_struct), []) if j not in used_gstr2b]
                if not candidates:
                    continue

                ig_s = row_agg["IGST"]
                cg_s = row_agg["CGST"]
                sg_s = row_agg["SGST"]

                for j in candidates:
                    if (
                        abs(gstr2b_igst[j] - ig_s) <= TOLERANCE and
                        abs(gstr2b_cgst[j] - cg_s) <= TOLERANCE and
                        abs(gstr2b_sgst[j] - sg_s) <= TOLERANCE
                    ):
                        grp = list(books_group_indices[(gst_c, inv_c)])
                        matched_books_indices.extend(grp)
                        matched_gstr2b_indices.append(j)
                        used_books.update(grp)
                        used_gstr2b.add(j)
                        break

        diag["step5a_books_matched"] = len(matched_books_indices)
        diag["step5a_gstr2b_matched"] = len(matched_gstr2b_indices)

        # Step 5B
        gstr2b_gstin_tax_buckets = defaultdict(list)
        for row in gstr2b.itertuples():
            if row.Index not in used_gstr2b:
                gst_c = getattr(row, "GSTIN_CLEAN", "")
                if gst_c != "":
                    key = (
                        gst_c,
                        getattr(row, "TAX_STRUCTURE", ""),
                        int(round(gstr2b_igst[row.Index])),
                        int(round(gstr2b_cgst[row.Index])),
                        int(round(gstr2b_sgst[row.Index]))
                    )
                    gstr2b_gstin_tax_buckets[key].append(row.Index)

        books_igst = books["IGST"].to_dict()
        books_cgst = books["CGST"].to_dict()
        books_sgst = books["SGST"].to_dict()
        books_tax = books["TAX_STRUCTURE"].to_dict()
        books_gstin = books["GSTIN_CLEAN"].to_dict()

        for b_idx in books.index:
            if b_idx in used_books:
                continue
            gst_c = books_gstin.get(b_idx, "")
            if not gst_c:
                continue

            tax_struct = books_tax.get(b_idx, "")
            ig_val = books_igst.get(b_idx, 0)
            cg_val = books_cgst.get(b_idx, 0)
            sg_val = books_sgst.get(b_idx, 0)

            round_ig = int(round(ig_val))
            round_cg = int(round(cg_val))
            round_sg = int(round(sg_val))

            found = False
            for d_i in (0, -1, 1):
                for d_c in (0, -1, 1):
                    for d_s in (0, -1, 1):
                        search_key = (gst_c, tax_struct, round_ig + d_i, round_cg + d_c, round_sg + d_s)
                        candidates = gstr2b_gstin_tax_buckets.get(search_key)
                        if not candidates:
                            continue
                        for j in candidates:
                            if j in used_gstr2b:
                                continue
                            if (
                                abs(gstr2b_igst[j] - ig_val) <= TOLERANCE and
                                abs(gstr2b_cgst[j] - cg_val) <= TOLERANCE and
                                abs(gstr2b_sgst[j] - sg_val) <= TOLERANCE
                            ):
                                matched_books_indices.append(b_idx)
                                matched_gstr2b_indices.append(j)
                                used_books.add(b_idx)
                                used_gstr2b.add(j)
                                found = True
                                break
                        if found:
                            break
                    if found:
                        break
                if found:
                    break

        diag["total_books_matched"] = len(matched_books_indices)
        diag["total_gstr2b_matched"] = len(matched_gstr2b_indices)
        diag["step5b_books_added"] = len(matched_books_indices) - diag["step5a_books_matched"]

        # Type diagnostics
        sample_igst_vals = list(gstr2b_igst.values())[:3]
        diag["gstr2b_igst_val_types"] = [str(type(v).__name__) for v in sample_igst_vals]
        diag["gstr2b_igst_val_samples"] = [float(v) for v in sample_igst_vals]
        
        # Index type diagnostics
        sample_book_idx = list(books.index)[:3]
        diag["books_index_types"] = [str(type(i).__name__) for i in sample_book_idx]
        
        # Check used_books type
        sample_used = list(used_books)[:3]
        diag["used_books_types"] = [str(type(i).__name__) for i in sample_used]
        
        # Bucket stats
        diag["gstr2b_bucket_count"] = len(gstr2b_gstin_tax_buckets)
        bucket_sizes = [len(v) for v in gstr2b_gstin_tax_buckets.values()]
        diag["gstr2b_bucket_total_entries"] = sum(bucket_sizes)
        
        # Count books entries that could participate in 5B
        eligible_5b_books = sum(1 for b_idx in books.index if b_idx not in used_books and books_gstin.get(b_idx, ""))
        diag["eligible_5b_books"] = eligible_5b_books
        
        # Rounding check
        import math
        diag["round_22_5"] = round(22.5)
        diag["round_2562_5"] = round(2562.5)
        diag["floor_22_5_plus_0_5"] = int(math.floor(22.5 + 0.5))
        diag["floor_2562_5_plus_0_5"] = int(math.floor(2562.5 + 0.5))

        # Cleanup
        try:
            os.remove(input_path)
        except Exception:
            pass

        return diag

    except Exception as e:
        import traceback
        diag["error"] = str(e)
        diag["traceback"] = traceback.format_exc()
        return diag, 500

@app.route('/download-template')
def download_template():
    return send_file('static/files/gst_reco_template.xlsx', as_attachment=True, download_name='GST_Reco_Template.xlsx')

if __name__ == '__main__':
    import webbrowser
    from threading import Timer
    
    def open_browser():
        if not os.environ.get("WERKZEUG_RUN_MAIN"):
            webbrowser.open_new('http://127.0.0.1:5000/')

    Timer(1, open_browser).start()
    app.run(host='0.0.0.0', debug=True, port=5000)
