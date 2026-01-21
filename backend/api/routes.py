"""API routes for document processing."""
from flask import Blueprint, request, jsonify, send_file
from werkzeug.utils import secure_filename
import os
import tempfile
import time
import uuid
import pandas as pd

from services.ey_processor import process_pdf_to_final_df_ey, process_ey_json_to_df
from services.pwc_processor import process_pdf_to_final_df_pwc, process_pwc_json_to_df
from services.ifrs_processor import process_ifrs_path_to_df, process_ifrs_folder_to_df
from services.faiss_builder import build_faiss_from_df_unified
from utils.config import get_faiss_dir, get_doc_name

api = Blueprint('api', __name__)

# Store temp CSV files for download
_csv_storage = {}


@api.route('/config', methods=['GET'])
def get_config():
    """Get application configuration."""
    return jsonify({
        "pipelines": ["ey", "pwc", "ifrs", "combined"],
        "max_upload_size_mb": 500,
        "supported_formats": ["pdf", "json", "zip"]
    })


@api.route('/process/ey', methods=['POST'])
def process_ey():
    """
    Process EY PDF file.

    Expected request:
    - file: PDF file (multipart/form-data)

    Returns:
    - chunks_count: Number of chunks processed
    - processing_time_minutes: Time taken
    - preview_data: First 1000 rows
    - download_token: Token for CSV download
    """
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400

    if not (file.filename.endswith('.pdf') or file.filename.endswith('.json')):
        return jsonify({"error": "Only PDF/JSON files are supported"}), 400

    try:
        start_time = time.time()

        ext = ".pdf" if file.filename.endswith(".pdf") else ".json"

        # Save uploaded file to temp directory
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp_file:
            file.save(tmp_file.name)
            tmp_path = tmp_file.name

        try:
            # Process PDF or JSON
            if ext == ".json":
                df = process_ey_json_to_df(tmp_path)
            else:
                df = process_pdf_to_final_df_ey(tmp_path)

            if df.empty:
                return jsonify({"error": "No content extracted from file"}), 400

            # Build FAISS index
            faiss_dir = get_faiss_dir("EY")
            build_faiss_from_df_unified(df, faiss_dir)

            # Generate CSV for download
            token = str(uuid.uuid4())
            csv_path = os.path.join(tempfile.gettempdir(), f"{token}.csv")
            df.to_csv(csv_path, index=False)
            _csv_storage[token] = csv_path

            # Calculate processing time
            elapsed = time.time() - start_time
            elapsed_minutes = elapsed / 60

            # Return response
            return jsonify({
                "success": True,
                "chunks_count": len(df),
                "processing_time_minutes": round(elapsed_minutes, 2),
                "preview_data": df.head(1000).to_dict('records'),
                "download_token": token,
                "doc_name": get_doc_name("EY"),
                "publisher": "EY"
            })

        finally:
            # Clean up temp PDF
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    except Exception as e:
        return jsonify({
            "error": "Processing failed",
            "message": str(e)
        }), 500


@api.route('/process/pwc', methods=['POST'])
def process_pwc():
    """
    Process PwC PDF file.

    Expected request:
    - file: PDF file (multipart/form-data)

    Returns:
    - chunks_count: Number of chunks processed
    - processing_time_minutes: Time taken
    - preview_data: First 1000 rows
    - download_token: Token for CSV download
    """
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400

    if not (file.filename.endswith('.pdf') or file.filename.endswith('.json')):
        return jsonify({"error": "Only PDF/JSON files are supported"}), 400

    try:
        start_time = time.time()

        ext = ".pdf" if file.filename.endswith(".pdf") else ".json"

        # Save uploaded file to temp directory
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp_file:
            file.save(tmp_file.name)
            tmp_path = tmp_file.name

        try:
            # Process PDF or JSON
            if ext == ".json":
                df = process_pwc_json_to_df(tmp_path)
            else:
                df = process_pdf_to_final_df_pwc(tmp_path)

            if df.empty:
                return jsonify({"error": "No content extracted from file"}), 400

            # Build FAISS index
            faiss_dir = get_faiss_dir("PwC")
            build_faiss_from_df_unified(df, faiss_dir)

            # Generate CSV for download
            token = str(uuid.uuid4())
            csv_path = os.path.join(tempfile.gettempdir(), f"{token}.csv")
            df.to_csv(csv_path, index=False)
            _csv_storage[token] = csv_path

            # Calculate processing time
            elapsed = time.time() - start_time
            elapsed_minutes = elapsed / 60

            # Return response
            return jsonify({
                "success": True,
                "chunks_count": len(df),
                "processing_time_minutes": round(elapsed_minutes, 2),
                "preview_data": df.head(1000).to_dict('records'),
                "download_token": token,
                "doc_name": get_doc_name("PwC"),
                "publisher": "PwC"
            })

        finally:
            # Clean up temp PDF
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    except Exception as e:
        return jsonify({
            "error": "Processing failed",
            "message": str(e)
        }), 500


@api.route('/process/ifrs', methods=['POST'])
def process_ifrs():
    """
    Process IFRS A/B/C files.

    Expected request:
    - mode: "upload" or "folder"
    - ifrs_a_files: List of files for IFRS A (if mode=upload)
    - ifrs_b_files: List of files for IFRS B (if mode=upload)
    - ifrs_c_files: List of files for IFRS C (if mode=upload)
    - ifrs_a_path: Folder path for IFRS A (if mode=folder)
    - ifrs_b_path: Folder path for IFRS B (if mode=folder)
    - ifrs_c_path: Folder path for IFRS C (if mode=folder)

    Returns:
    - ifrs_a: {chunks_count, download_token}
    - ifrs_b: {chunks_count, download_token}
    - ifrs_c: {chunks_count, download_token}
    - total_time_minutes: Total processing time
    """
    mode = request.form.get('mode', 'upload')

    try:
        start_time = time.time()

        if mode == 'folder':
            # Process from folder paths
            ifrs_a_path = request.form.get('ifrs_a_path')
            ifrs_b_path = request.form.get('ifrs_b_path')
            ifrs_c_path = request.form.get('ifrs_c_path')

            if not (ifrs_a_path and ifrs_b_path and ifrs_c_path):
                return jsonify({"error": "All three folder paths required"}), 400

            # Process IFRS A
            df_a = process_ifrs_folder_to_df(ifrs_a_path, get_doc_name("IFRS_A"))
            faiss_dir_a = get_faiss_dir("IFRS_A")
            build_faiss_from_df_unified(df_a, faiss_dir_a)

            # Generate CSV for A
            token_a = str(uuid.uuid4())
            csv_path_a = os.path.join(tempfile.gettempdir(), f"{token_a}.csv")
            df_a.to_csv(csv_path_a, index=False)
            _csv_storage[token_a] = csv_path_a

            # Process IFRS B
            df_b = process_ifrs_folder_to_df(ifrs_b_path, get_doc_name("IFRS_B"))
            faiss_dir_b = get_faiss_dir("IFRS_B")
            build_faiss_from_df_unified(df_b, faiss_dir_b)

            # Generate CSV for B
            token_b = str(uuid.uuid4())
            csv_path_b = os.path.join(tempfile.gettempdir(), f"{token_b}.csv")
            df_b.to_csv(csv_path_b, index=False)
            _csv_storage[token_b] = csv_path_b

            # Process IFRS C
            df_c = process_ifrs_folder_to_df(ifrs_c_path, get_doc_name("IFRS_C"))
            faiss_dir_c = get_faiss_dir("IFRS_C")
            build_faiss_from_df_unified(df_c, faiss_dir_c)

            # Generate CSV for C
            token_c = str(uuid.uuid4())
            csv_path_c = os.path.join(tempfile.gettempdir(), f"{token_c}.csv")
            df_c.to_csv(csv_path_c, index=False)
            _csv_storage[token_c] = csv_path_c

        else:  # upload mode
            # Process uploaded files
            ifrs_a_files = request.files.getlist('ifrs_a_files')
            ifrs_b_files = request.files.getlist('ifrs_b_files')
            ifrs_c_files = request.files.getlist('ifrs_c_files')

            if not (ifrs_a_files and ifrs_b_files and ifrs_c_files):
                return jsonify({"error": "Files required for all three IFRS parts"}), 400

            # Process IFRS A files
            dfs_a = []
            for f in ifrs_a_files:
                file_ext = os.path.splitext(f.filename)[1].lower()
                is_zip = file_ext == '.zip'

                with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp:
                    f.save(tmp.name)
                    tmp_path = tmp.name

                try:
                    if is_zip:
                        # For ZIP files, use process_ifrs_folder_to_df which handles extraction and cleanup
                        df = process_ifrs_folder_to_df(tmp_path, get_doc_name("IFRS_A"))
                    else:
                        # For PDF/JSON files, use process_ifrs_path_to_df
                        df = process_ifrs_path_to_df(tmp_path, get_doc_name("IFRS_A"))
                    dfs_a.append(df)
                finally:
                    # Only cleanup non-ZIP files (ZIP cleanup is handled by process_ifrs_folder_to_df)
                    if not is_zip and os.path.exists(tmp_path):
                        try:
                            os.unlink(tmp_path)
                        except Exception as e:
                            print(f"Warning: Could not delete temp file {tmp_path}: {e}")

            df_a = pd.concat(dfs_a, ignore_index=True) if dfs_a else pd.DataFrame()
            faiss_dir_a = get_faiss_dir("IFRS_A")
            build_faiss_from_df_unified(df_a, faiss_dir_a)

            token_a = str(uuid.uuid4())
            csv_path_a = os.path.join(tempfile.gettempdir(), f"{token_a}.csv")
            df_a.to_csv(csv_path_a, index=False)
            _csv_storage[token_a] = csv_path_a

            # Process IFRS B files
            dfs_b = []
            for f in ifrs_b_files:
                file_ext = os.path.splitext(f.filename)[1].lower()
                is_zip = file_ext == '.zip'

                with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp:
                    f.save(tmp.name)
                    tmp_path = tmp.name

                try:
                    if is_zip:
                        # For ZIP files, use process_ifrs_folder_to_df which handles extraction and cleanup
                        df = process_ifrs_folder_to_df(tmp_path, get_doc_name("IFRS_B"))
                    else:
                        # For PDF/JSON files, use process_ifrs_path_to_df
                        df = process_ifrs_path_to_df(tmp_path, get_doc_name("IFRS_B"))
                    dfs_b.append(df)
                finally:
                    # Only cleanup non-ZIP files (ZIP cleanup is handled by process_ifrs_folder_to_df)
                    if not is_zip and os.path.exists(tmp_path):
                        try:
                            os.unlink(tmp_path)
                        except Exception as e:
                            print(f"Warning: Could not delete temp file {tmp_path}: {e}")

            df_b = pd.concat(dfs_b, ignore_index=True) if dfs_b else pd.DataFrame()
            faiss_dir_b = get_faiss_dir("IFRS_B")
            build_faiss_from_df_unified(df_b, faiss_dir_b)

            token_b = str(uuid.uuid4())
            csv_path_b = os.path.join(tempfile.gettempdir(), f"{token_b}.csv")
            df_b.to_csv(csv_path_b, index=False)
            _csv_storage[token_b] = csv_path_b

            # Process IFRS C files
            dfs_c = []
            for f in ifrs_c_files:
                file_ext = os.path.splitext(f.filename)[1].lower()
                is_zip = file_ext == '.zip'

                with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp:
                    f.save(tmp.name)
                    tmp_path = tmp.name

                try:
                    if is_zip:
                        # For ZIP files, use process_ifrs_folder_to_df which handles extraction and cleanup
                        df = process_ifrs_folder_to_df(tmp_path, get_doc_name("IFRS_C"))
                    else:
                        # For PDF/JSON files, use process_ifrs_path_to_df
                        df = process_ifrs_path_to_df(tmp_path, get_doc_name("IFRS_C"))
                    dfs_c.append(df)
                finally:
                    # Only cleanup non-ZIP files (ZIP cleanup is handled by process_ifrs_folder_to_df)
                    if not is_zip and os.path.exists(tmp_path):
                        try:
                            os.unlink(tmp_path)
                        except Exception as e:
                            print(f"Warning: Could not delete temp file {tmp_path}: {e}")

            df_c = pd.concat(dfs_c, ignore_index=True) if dfs_c else pd.DataFrame()
            faiss_dir_c = get_faiss_dir("IFRS_C")
            build_faiss_from_df_unified(df_c, faiss_dir_c)

            token_c = str(uuid.uuid4())
            csv_path_c = os.path.join(tempfile.gettempdir(), f"{token_c}.csv")
            df_c.to_csv(csv_path_c, index=False)
            _csv_storage[token_c] = csv_path_c

        # Calculate total time
        elapsed = time.time() - start_time
        elapsed_minutes = elapsed / 60

        return jsonify({
            "success": True,
            "ifrs_a": {
                "chunks_count": len(df_a),
                "download_token": token_a,
                "doc_name": get_doc_name("IFRS_A"),
                "preview_data": df_a.head(1000).to_dict('records') if not df_a.empty else []
            },
            "ifrs_b": {
                "chunks_count": len(df_b),
                "download_token": token_b,
                "doc_name": get_doc_name("IFRS_B"),
                "preview_data": df_b.head(1000).to_dict('records') if not df_b.empty else []
            },
            "ifrs_c": {
                "chunks_count": len(df_c),
                "download_token": token_c,
                "doc_name": get_doc_name("IFRS_C"),
                "preview_data": df_c.head(1000).to_dict('records') if not df_c.empty else []
            },
            "total_time_minutes": round(elapsed_minutes, 2)
        })

    except Exception as e:
        return jsonify({
            "error": "IFRS processing failed",
            "message": str(e)
        }), 500


@api.route('/process/combined', methods=['POST'])
def process_combined():
    """
    Process EY + PwC combined.

    Expected request:
    - ey_file: EY PDF file (multipart/form-data)
    - pwc_file: PwC PDF file (multipart/form-data)

    Returns:
    - total_chunks: Combined chunk count
    - ey_chunks: EY chunk count
    - pwc_chunks: PwC chunk count
    - processing_time_minutes: Time taken
    - download_token: Token for CSV download
    """
    if 'ey_file' not in request.files or 'pwc_file' not in request.files:
        return jsonify({"error": "Both EY and PwC files required"}), 400

    ey_file = request.files['ey_file']
    pwc_file = request.files['pwc_file']

    if ey_file.filename == '' or pwc_file.filename == '':
        return jsonify({"error": "No file selected"}), 400

    if not (ey_file.filename.endswith(('.pdf', '.json')) and pwc_file.filename.endswith(('.pdf', '.json'))):
        return jsonify({"error": "Only PDF/JSON files are supported"}), 400

    try:
        start_time = time.time()

        ey_ext = ".pdf" if ey_file.filename.endswith(".pdf") else ".json"
        pwc_ext = ".pdf" if pwc_file.filename.endswith(".pdf") else ".json"

        # Save EY file and process
        with tempfile.NamedTemporaryFile(delete=False, suffix=ey_ext) as ey_tmp:
            ey_file.save(ey_tmp.name)
            ey_tmp_path = ey_tmp.name

        try:
            if ey_ext == ".json":
                df_ey = process_ey_json_to_df(ey_tmp_path)
            else:
                df_ey = process_pdf_to_final_df_ey(ey_tmp_path)
        finally:
            if os.path.exists(ey_tmp_path):
                os.unlink(ey_tmp_path)

        # Save PwC file and process
        with tempfile.NamedTemporaryFile(delete=False, suffix=pwc_ext) as pwc_tmp:
            pwc_file.save(pwc_tmp.name)
            pwc_tmp_path = pwc_tmp.name

        try:
            if pwc_ext == ".json":
                df_pwc = process_pwc_json_to_df(pwc_tmp_path)
            else:
                df_pwc = process_pdf_to_final_df_pwc(pwc_tmp_path)
        finally:
            if os.path.exists(pwc_tmp_path):
                os.unlink(pwc_tmp_path)

        # Combine DataFrames
        df_combined = pd.concat([df_ey, df_pwc], ignore_index=True)

        if df_combined.empty:
            return jsonify({"error": "No content extracted from files"}), 400

        # Build combined FAISS index from config.yaml
        faiss_dir = get_faiss_dir("Combined")

        build_faiss_from_df_unified(df_combined, faiss_dir)

        # Generate CSV for download
        token = str(uuid.uuid4())
        csv_path = os.path.join(tempfile.gettempdir(), f"{token}.csv")
        df_combined.to_csv(csv_path, index=False)
        _csv_storage[token] = csv_path

        # Calculate processing time
        elapsed = time.time() - start_time
        elapsed_minutes = elapsed / 60

        return jsonify({
            "success": True,
            "total_chunks": len(df_combined),
            "ey_chunks": len(df_ey),
            "pwc_chunks": len(df_pwc),
            "processing_time_minutes": round(elapsed_minutes, 2),
            "download_token": token,
            "preview_data": df_combined.head(1000).to_dict('records')
        })

    except Exception as e:
        return jsonify({
            "error": "Combined processing failed",
            "message": str(e)
        }), 500


@api.route('/download/csv/<token>', methods=['GET'])
def download_csv(token):
    """
    Download CSV file for processed data.

    Args:
        token: Download token returned by processing endpoint

    Returns:
        CSV file
    """
    if token not in _csv_storage:
        return jsonify({"error": "Invalid or expired download token"}), 404

    csv_path = _csv_storage[token]

    if not os.path.exists(csv_path):
        del _csv_storage[token]
        return jsonify({"error": "CSV file not found"}), 404

    try:
        return send_file(
            csv_path,
            mimetype='text/csv',
            as_attachment=True,
            download_name='processed_data.csv'
        )
    finally:
        # Clean up after download
        try:
            os.unlink(csv_path)
            del _csv_storage[token]
        except Exception:
            pass  # Ignore cleanup errors
