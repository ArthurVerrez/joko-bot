# ./app/app.py
from flask import (
    Flask,
    render_template,
    url_for,
    request,
    redirect,
    flash,
    jsonify,
    abort,
)
import pandas as pd
import os
import json
from datetime import datetime, date
import uuid
import re
from dotenv import load_dotenv
import hmac
import hashlib

app = Flask(__name__)
app.secret_key = "your_very_secret_key_for_everything"

# Load environment variables from .env at the root of ./app
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
NOTION_VERIFICATION_TOKEN = os.getenv("NOTION_INTEGRATION_SECRET")

# --- Configuration ---
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
MERCHANTS_FILE = os.path.join(DATA_DIR, "merchants.csv")
OFFERS_FILE = os.path.join(DATA_DIR, "offers.csv")

# --- Hardcoded Condition Mapping ---
PREDEFINED_CONDITIONS_MAP = {
    "cond_no_cashback_giftcard": "Achats via bon d'achat ou carte cadeau non compatibles avec le cashback",
    "cond_specific": "Conditions spécifiques",
    "cond_has_validation_delay_info": "Délai de validation du cashback",
    "cond_has_tracking_delay_info": "Délai d'apparition du cashback en attente",
    "cond_cashback_on_nett_amount": "Le cashback est calculé sur le montant hors taxes et autres frais",
    "cond_no_cashback_if_cancelled_simple": "Le cashback ne sera pas attribué en cas d'annulation",
    "cond_no_cashback_if_subscription_incomplete": "Le cashback ne sera pas attribué en cas de non finalisation de la souscription",
    "cond_no_cashback_if_returned_or_cancelled": "Le cashback ne sera pas attribué en cas de retour ou d'annulation",
    "cond_cookies_must_be_accepted": "Les cookies doivent être acceptés",
    "cond_has_legal_warnings": "Mentions légales et mises en garde",
    "cond_new_clients_only": "Nouveaux clients uniquement",
    "cond_has_ineligible_products": "Produits non éligibles au cashback",
    "cond_joko_codes_only_with_cashback": "Seuls les codes promo fournis par Joko sont garantis d'être cumulables avec le cashback",
    "cond_has_cashback_validation_steps": "Étapes à suivre pour la validation du cashback",
}


# --- Helper function to parse offer amount (from previous version) ---
def parse_offer_amount_to_ratio(offer_amount_str):
    if pd.isna(offer_amount_str) or not isinstance(offer_amount_str, str):
        return None
    offer_amount_str = str(offer_amount_str).replace(",", ".")
    match_percent = re.search(r"(\d+\.?\d*)\s*%", offer_amount_str)
    if match_percent:
        return float(match_percent.group(1)) / 100.0
    return None


# --- Load Data ---
merchants_df = pd.DataFrame()
offers_df = pd.DataFrame()


def load_data():
    global merchants_df, offers_df
    # Load Merchants
    try:
        merchants_df = pd.read_csv(MERCHANTS_FILE)
        if not merchants_df.empty:
            merchants_df["merchant_id"] = merchants_df["merchant_id"].astype(str)
        else:
            merchants_df = pd.DataFrame(
                columns=[
                    "merchant_id",
                    "banner_img_url",
                    "merchant_image_url",
                    "merchant_name",
                    "merchant_days",
                    "about_text",
                ]
            )
        print(f"Loaded {len(merchants_df)} merchants.")
    except FileNotFoundError:
        print(
            f"Error: {MERCHANTS_FILE} not found. Initializing empty merchants DataFrame."
        )
        merchants_df = pd.DataFrame(
            columns=[
                "merchant_id",
                "banner_img_url",
                "merchant_image_url",
                "merchant_name",
                "merchant_days",
                "about_text",
            ]
        )
    except Exception as e:
        print(f"Error loading merchants.csv: {e}")
        merchants_df = pd.DataFrame(
            columns=[
                "merchant_id",
                "banner_img_url",
                "merchant_image_url",
                "merchant_name",
                "merchant_days",
                "about_text",
            ]
        )

    # Load Offers
    try:
        offers_df = pd.read_csv(OFFERS_FILE)
        if not offers_df.empty:
            offers_df["merchant_id"] = offers_df["merchant_id"].astype(str)
            offers_df["offer_id"] = offers_df["offer_id"].astype(str)

            bool_cols_to_process = list(PREDEFINED_CONDITIONS_MAP.keys())
            if (
                "available" not in bool_cols_to_process
                and "available" in offers_df.columns
            ):
                bool_cols_to_process.append("available")

            for col_name in bool_cols_to_process:
                if col_name in offers_df.columns:
                    offers_df[col_name] = (
                        offers_df[col_name]
                        .apply(
                            lambda x: (
                                True
                                if str(x).strip().lower() == "true"
                                else (False if pd.notna(x) else False)
                            )
                        )
                        .astype(bool)
                    )
        else:
            # Ensure all expected columns exist, especially boolean ones
            expected_offer_cols = [
                "offer_id",
                "merchant_id",
                "amount_ratio",
                "original_offer_amount",
                "offer_description",
                "end_date",
                "imagined_cashback_code",
                "available",
            ] + list(PREDEFINED_CONDITIONS_MAP.keys())
            offers_df = pd.DataFrame(columns=expected_offer_cols)

        print(f"Loaded {len(offers_df)} offers.")
    except FileNotFoundError:
        print(f"Error: {OFFERS_FILE} not found. Initializing empty offers DataFrame.")
        expected_offer_cols = [
            "offer_id",
            "merchant_id",
            "amount_ratio",
            "original_offer_amount",
            "offer_description",
            "end_date",
            "imagined_cashback_code",
            "available",
        ] + list(PREDEFINED_CONDITIONS_MAP.keys())
        offers_df = pd.DataFrame(columns=expected_offer_cols)
    except Exception as e:
        print(f"Error loading offers.csv: {e}")
        expected_offer_cols = [
            "offer_id",
            "merchant_id",
            "amount_ratio",
            "original_offer_amount",
            "offer_description",
            "end_date",
            "imagined_cashback_code",
            "available",
        ] + list(PREDEFINED_CONDITIONS_MAP.keys())
        offers_df = pd.DataFrame(columns=expected_offer_cols)

    if not merchants_df.empty:
        merchants_df = merchants_df.fillna("")
    if not offers_df.empty:
        string_cols = [
            "imagined_cashback_code",
            "original_offer_amount",
            "offer_description",
            "end_date",
        ]
        for col in string_cols:
            if col in offers_df.columns:
                offers_df[col] = offers_df[col].fillna("")
        # Ensure boolean columns default to False if they were created empty
        for col in list(PREDEFINED_CONDITIONS_MAP.keys()) + ["available"]:
            if col in offers_df.columns and offers_df[col].isnull().any():
                offers_df[col] = offers_df[col].fillna(False).astype(bool)


load_data()


@app.route("/")
def index():
    # ... (index route remains mostly the same) ...
    filter_merchant_id = request.args.get("merchant_id", None)
    filter_offer_id = request.args.get("offer_id", None)
    include_staging_str = request.args.get("include_staging", "false")
    include_staging = include_staging_str.lower() == "true"

    display_offers_data = []
    # Ensure DataFrames are not empty before proceeding
    if offers_df.empty:
        print("Warning: Offers DataFrame is empty. No offers to display.")
    elif (
        merchants_df.empty and not offers_df.empty
    ):  # if offers exist but no merchants to merge
        print(
            "Warning: Merchants DataFrame is empty. Offer details might be incomplete."
        )
        # Decide how to handle: show offers with no merchant info or show nothing
        # For now, let's proceed and merchant details will be blank

    current_offers_df = offers_df.copy()

    if not current_offers_df.empty:
        if not include_staging:
            if "available" in current_offers_df.columns:
                current_offers_df = current_offers_df[
                    current_offers_df["available"] == True
                ]
            else:
                print("Warning: 'available' column not found in offers_df.")

        if filter_merchant_id:
            current_offers_df = current_offers_df[
                current_offers_df["merchant_id"] == filter_merchant_id
            ]
        if filter_offer_id:
            current_offers_df = current_offers_df[
                current_offers_df["offer_id"] == filter_offer_id
            ]

        # Perform merge only if merchants_df is not empty
        if not merchants_df.empty:
            merged_df = pd.merge(
                current_offers_df,
                merchants_df[
                    [
                        "merchant_id",
                        "merchant_name",
                        "merchant_image_url",
                        "banner_img_url",
                        "merchant_days",
                        "about_text",
                    ]
                ],
                on="merchant_id",
                how="left",  # Use left merge to keep all filtered offers
            )
            merged_df.fillna("", inplace=True)
        else:  # If merchants_df is empty, use current_offers_df directly (merchant details will be missing)
            merged_df = current_offers_df.copy()
            # Add missing merchant columns as empty strings for template consistency
            for col in [
                "merchant_name",
                "merchant_image_url",
                "banner_img_url",
                "merchant_days",
                "about_text",
            ]:
                if col not in merged_df.columns:
                    merged_df[col] = ""

        for _, row in merged_df.iterrows():
            offer_card_data = {
                "offer_id": row.get("offer_id", ""),
                "merchant_name": row.get("merchant_name", "N/A"),
                "merchant_image_url": row.get("merchant_image_url", ""),
                "banner_img_url": row.get("banner_img_url", ""),
                "offer_description": row.get("offer_description", ""),
                "original_offer_amount": row.get("original_offer_amount", ""),
                "merchant_days": row.get("merchant_days", ""),
                "merchant_subtitle_display": "",
                "about_text_short": (
                    row.get("about_text", "")[:100] + "..."
                    if row.get("about_text", "")
                    and len(row.get("about_text", "")) > 100
                    else row.get("about_text", "")
                ),
                "active_conditions": [],
                "imagined_cashback_code": row.get("imagined_cashback_code", ""),
                "is_available": (
                    row.get("available", False) if "available" in row else False
                ),
            }

            if (
                pd.notna(row.get("original_offer_amount"))
                and row.get("original_offer_amount") != ""
            ):
                offer_card_data["merchant_subtitle_display"] = (
                    f"Jusqu'à {row.get('original_offer_amount','')} de cashback"
                )
            elif (
                pd.notna(row.get("amount_ratio"))
                and str(row.get("amount_ratio")).strip() != ""
            ):  # Check for non-empty string
                try:
                    ratio_val_str = str(row.get("amount_ratio")).replace(",", ".")
                    if ratio_val_str:
                        ratio_val = float(ratio_val_str) * 100
                        if ratio_val.is_integer():
                            offer_card_data["merchant_subtitle_display"] = (
                                f"Jusqu'à {int(ratio_val)}% de cashback"
                            )
                        else:
                            offer_card_data["merchant_subtitle_display"] = (
                                f"Jusqu'à {ratio_val:.1f}% de cashback"
                            )
                except (ValueError, TypeError):
                    pass

            for cond_col_name, full_condition_text in PREDEFINED_CONDITIONS_MAP.items():
                if cond_col_name in row and row[cond_col_name] is True:
                    offer_card_data["active_conditions"].append(full_condition_text)

            display_offers_data.append(offer_card_data)
    else:  # offers_df is empty initially
        print("Warning: Offers data is empty or filters resulted in no offers.")

    return render_template(
        "index.html",
        offers=display_offers_data,
        filtered_merchant_id=filter_merchant_id,
        filtered_offer_id=filter_offer_id,
        include_staging=include_staging,
    )


@app.route("/edit_offer/<offer_id>", methods=["GET", "POST"])
def edit_offer(offer_id):
    # ... (edit_offer route remains the same) ...
    global offers_df

    if offers_df.empty:
        flash("Offers data not loaded. Cannot edit.", "error")
        return redirect(url_for("index"))

    offer_row_index = offers_df[offers_df["offer_id"] == offer_id].index
    if offer_row_index.empty:
        flash(f"Offer with ID {offer_id} not found.", "error")
        return redirect(url_for("index"))

    offer_index = offer_row_index[0]

    if request.method == "POST":
        try:
            offers_df.loc[offer_index, "original_offer_amount"] = request.form.get(
                "original_offer_amount", ""
            )
            offers_df.loc[offer_index, "offer_description"] = request.form.get(
                "offer_description", ""
            )
            offers_df.loc[offer_index, "imagined_cashback_code"] = request.form.get(
                "imagined_cashback_code", ""
            )

            end_date_str = request.form.get("end_date", "")
            if end_date_str:
                try:
                    datetime.strptime(end_date_str, "%Y-%m-%d")
                    offers_df.loc[offer_index, "end_date"] = end_date_str
                except ValueError:
                    flash("Invalid end_date format. Please use YYYY-MM-DD.", "warning")
                    # Keep old value if format is wrong
                    # offers_df.loc[offer_index, 'end_date'] = offers_df.loc[offer_index, 'end_date']
            else:
                offers_df.loc[offer_index, "end_date"] = (
                    ""  # Set to empty string if blank
                )

            offers_df.loc[offer_index, "available"] = (
                True if request.form.get("available") == "True" else False
            )

            for col_name in PREDEFINED_CONDITIONS_MAP.keys():
                offers_df.loc[offer_index, col_name] = (
                    True if request.form.get(col_name) == "True" else False
                )

            offers_df.to_csv(OFFERS_FILE, index=False, encoding="utf-8")
            print(f"Offer {offer_id} updated and offers.csv saved.")
            flash(f"Offer {offer_id} updated successfully!", "success")
            return redirect(url_for("index", offer_id=offer_id, include_staging="true"))

        except Exception as e:
            print(f"Error updating offer {offer_id}: {e}")
            flash(f"Error updating offer: {e}", "error")
            offer_data_for_form = offers_df.loc[offer_index].fillna("").to_dict()
            offer_data_for_form["available_for_edit_form"] = False
            return render_template(
                "edit_offer.html",
                offer=offer_data_for_form,
                offer_for_form=offer_data_for_form,
                predefined_conditions_map=PREDEFINED_CONDITIONS_MAP,
            )

    offer_data = offers_df.loc[offer_index].fillna("").to_dict()
    offer_data_for_form = offer_data.copy()
    offer_data_for_form["available_for_edit_form"] = False

    return render_template(
        "edit_offer.html",
        offer=offer_data,
        offer_for_form=offer_data_for_form,
        predefined_conditions_map=PREDEFINED_CONDITIONS_MAP,
    )


@app.route("/delete_offer/<offer_id>", methods=["POST"])
def delete_offer(offer_id):
    global offers_df
    print(f"Attempting to delete offer ID: {offer_id}")  # Log entry

    if offers_df.empty:
        print("Offers DataFrame is empty. Cannot delete.")  # Log
        flash("Offers data not loaded or empty. Cannot delete.", "error")
        return redirect(url_for("index", include_staging="true"))

    offer_row_index = offers_df[offers_df["offer_id"] == offer_id].index

    if offer_row_index.empty:
        print(f"Offer ID: {offer_id} not found for deletion.")  # Log
        flash(f"Offer with ID {offer_id} not found for deletion.", "error")
    else:
        try:
            offers_df.drop(offer_row_index, inplace=True)
            print(f"Offer ID: {offer_id} dropped from DataFrame.")  # Log
            offers_df.to_csv(OFFERS_FILE, index=False, encoding="utf-8")
            print(f"Offer ID: {offer_id} deleted and offers.csv saved.")  # Log
            flash(f"Offer {offer_id} deleted successfully!", "success")
        except Exception as e:
            print(
                f"Error during deletion or saving for offer ID {offer_id}: {e}"
            )  # Log
            flash(f"Error deleting offer {offer_id}: {e}", "error")

    return redirect(url_for("index", include_staging="true"))


# --- Merchant CRUD Routes (from previous step, ensure they are present) ---
@app.route("/merchants")
def merchants_list():
    sorted_merchants_df = (
        merchants_df.sort_values(by="merchant_name")
        if not merchants_df.empty
        else merchants_df
    )
    return render_template("merchants.html", merchants=sorted_merchants_df)


@app.route("/add_merchant", methods=["GET", "POST"])
def add_merchant():
    # ... (add_merchant route remains the same) ...
    global merchants_df
    if request.method == "POST":
        merchant_name = request.form.get("merchant_name")
        if not merchant_name:
            flash("Merchant Name is required.", "error")
            return render_template(
                "edit_merchant.html", merchant=None, is_add_mode=True
            )

        if not merchants_df[merchants_df["merchant_name"] == merchant_name].empty:
            flash(f'Merchant with name "{merchant_name}" already exists.', "warning")
            return render_template(
                "edit_merchant.html", merchant=request.form, is_add_mode=True
            )

        merchant_short_uuid = str(uuid.uuid4()).split("-")[0]
        new_merchant_id = f"mer_{merchant_short_uuid}".lower()

        new_merchant_data = {
            "merchant_id": new_merchant_id,
            "banner_img_url": request.form.get("banner_img_url", ""),
            "merchant_image_url": request.form.get("merchant_image_url", ""),
            "merchant_name": merchant_name,
            "merchant_days": request.form.get("merchant_days", ""),
            "about_text": request.form.get("about_text", ""),
        }

        new_row_df = pd.DataFrame([new_merchant_data])
        merchants_df = pd.concat([merchants_df, new_row_df], ignore_index=True)

        try:
            merchants_df.to_csv(MERCHANTS_FILE, index=False, encoding="utf-8")
            flash(
                f'Merchant "{merchant_name}" added successfully with ID {new_merchant_id}!',
                "success",
            )
            print(f"Merchant {new_merchant_id} added and merchants.csv saved.")
        except Exception as e:
            flash(f"Error saving merchant: {e}", "error")
            print(f"Error saving merchants.csv: {e}")

        return redirect(url_for("merchants_list"))

    return render_template("edit_merchant.html", merchant=None, is_add_mode=True)


@app.route("/edit_merchant/<merchant_id>", methods=["GET", "POST"])
def edit_merchant(merchant_id):
    # ... (edit_merchant route remains the same) ...
    global merchants_df
    if merchants_df.empty:
        flash("Merchants data not loaded. Cannot edit.", "error")
        return redirect(url_for("merchants_list"))

    merchant_row_index = merchants_df[merchants_df["merchant_id"] == merchant_id].index
    if merchant_row_index.empty:
        flash(f"Merchant with ID {merchant_id} not found.", "error")
        return redirect(url_for("merchants_list"))

    merchant_index = merchant_row_index[0]

    if request.method == "POST":
        updated_name = request.form.get("merchant_name")
        if not updated_name:
            flash("Merchant Name is required.", "error")
            current_merchant_data = (
                merchants_df.loc[merchant_index].fillna("").to_dict()
            )
            return render_template("edit_merchant.html", merchant=current_merchant_data)

        original_name = merchants_df.loc[merchant_index, "merchant_name"]
        if (
            updated_name != original_name
            and not merchants_df[merchants_df["merchant_name"] == updated_name].empty
        ):
            flash(
                f'Another merchant with name "{updated_name}" already exists.',
                "warning",
            )
            current_merchant_data_for_form = request.form.to_dict()
            current_merchant_data_for_form["merchant_id"] = merchant_id
            return render_template(
                "edit_merchant.html", merchant=current_merchant_data_for_form
            )

        merchants_df.loc[merchant_index, "banner_img_url"] = request.form.get(
            "banner_img_url", ""
        )
        merchants_df.loc[merchant_index, "merchant_image_url"] = request.form.get(
            "merchant_image_url", ""
        )
        merchants_df.loc[merchant_index, "merchant_name"] = updated_name
        merchants_df.loc[merchant_index, "merchant_days"] = request.form.get(
            "merchant_days", ""
        )
        merchants_df.loc[merchant_index, "about_text"] = request.form.get(
            "about_text", ""
        )

        try:
            merchants_df.to_csv(MERCHANTS_FILE, index=False, encoding="utf-8")
            flash(f"Merchant {merchant_id} updated successfully!", "success")
            print(f"Merchant {merchant_id} updated and merchants.csv saved.")
        except Exception as e:
            flash(f"Error saving merchant updates: {e}", "error")
            print(f"Error saving merchants.csv: {e}")

        return redirect(url_for("merchants_list"))

    merchant_data = merchants_df.loc[merchant_index].fillna("").to_dict()
    return render_template("edit_merchant.html", merchant=merchant_data)


@app.route("/delete_merchant/<merchant_id>", methods=["POST"])
def delete_merchant(merchant_id):
    # ... (delete_merchant route remains the same) ...
    global merchants_df, offers_df

    if merchants_df.empty:
        flash("Merchants data not loaded. Cannot delete.", "error")
        return redirect(url_for("merchants_list"))

    if not offers_df[offers_df["merchant_id"] == merchant_id].empty:
        flash(
            f"Cannot delete merchant {merchant_id}. It has associated offers. Please delete or reassign offers first.",
            "error",
        )
        return redirect(url_for("merchants_list"))

    merchant_row_index = merchants_df[merchants_df["merchant_id"] == merchant_id].index
    if merchant_row_index.empty:
        flash(f"Merchant with ID {merchant_id} not found for deletion.", "error")
        return redirect(url_for("merchants_list"))

    try:
        merchants_df.drop(merchant_row_index, inplace=True)
        merchants_df.to_csv(MERCHANTS_FILE, index=False, encoding="utf-8")
        flash(f"Merchant {merchant_id} deleted successfully!", "success")
        print(f"Merchant {merchant_id} deleted and merchants.csv saved.")
    except Exception as e:
        flash(f"Error deleting merchant: {e}", "error")
        print(f"Error deleting merchant {merchant_id}: {e}")

    return redirect(url_for("merchants_list"))


# --- New Add Offer Route ---
@app.route("/add_offer", methods=["GET", "POST"])
def add_offer():
    global offers_df
    if request.method == "POST":
        selected_merchant_id = request.form.get("merchant_id")
        offer_description = request.form.get("offer_description")

        if not selected_merchant_id:
            flash("Merchant selection is required.", "error")
            # Repopulate merchants for the dropdown on error
            merchants_for_dropdown = (
                merchants_df[["merchant_id", "merchant_name"]].to_dict(orient="records")
                if not merchants_df.empty
                else []
            )
            return render_template(
                "add_offer.html",
                merchants=merchants_for_dropdown,
                predefined_conditions_map=PREDEFINED_CONDITIONS_MAP,
                form_data=request.form,
            )

        if not offer_description:
            flash("Offer Description is required.", "error")
            merchants_for_dropdown = (
                merchants_df[["merchant_id", "merchant_name"]].to_dict(orient="records")
                if not merchants_df.empty
                else []
            )
            return render_template(
                "add_offer.html",
                merchants=merchants_for_dropdown,
                predefined_conditions_map=PREDEFINED_CONDITIONS_MAP,
                form_data=request.form,
            )

        offer_short_uuid = str(uuid.uuid4()).split("-")[0]
        new_offer_id = f"off_{offer_short_uuid}".lower()

        original_amount_str = request.form.get("original_offer_amount", "")
        amount_ratio_val = parse_offer_amount_to_ratio(original_amount_str)

        end_date_val = request.form.get("end_date", "")
        if end_date_val:
            try:
                datetime.strptime(end_date_val, "%Y-%m-%d")  # Validate
            except ValueError:
                flash(
                    "Invalid end_date format. Please use YYYY-MM-DD. End date not saved.",
                    "warning",
                )
                end_date_val = ""  # Clear if invalid

        new_offer_data = {
            "offer_id": new_offer_id,
            "merchant_id": selected_merchant_id,
            "amount_ratio": (
                amount_ratio_val if pd.notna(amount_ratio_val) else ""
            ),  # Store as empty string if None for CSV
            "original_offer_amount": original_amount_str,
            "offer_description": offer_description,
            "end_date": end_date_val,
            "imagined_cashback_code": request.form.get("imagined_cashback_code", ""),
            "available": True if request.form.get("available") == "True" else False,
        }

        for col_name in PREDEFINED_CONDITIONS_MAP.keys():
            new_offer_data[col_name] = (
                True if request.form.get(col_name) == "True" else False
            )

        new_row_df = pd.DataFrame([new_offer_data])
        offers_df = pd.concat([offers_df, new_row_df], ignore_index=True)

        try:
            offers_df.to_csv(OFFERS_FILE, index=False, encoding="utf-8")
            flash(
                f'Offer "{offer_description}" added successfully with ID {new_offer_id}!',
                "success",
            )
            print(f"Offer {new_offer_id} added and offers.csv saved.")
        except Exception as e:
            flash(f"Error saving new offer: {e}", "error")
            print(f"Error saving offers.csv: {e}")

        return redirect(
            url_for("index", merchant_id=selected_merchant_id, include_staging="true")
        )

    # GET request
    merchants_for_dropdown = (
        merchants_df[["merchant_id", "merchant_name"]].to_dict(orient="records")
        if not merchants_df.empty
        else []
    )
    return render_template(
        "add_offer.html",
        merchants=merchants_for_dropdown,
        predefined_conditions_map=PREDEFINED_CONDITIONS_MAP,
    )


@app.route("/notion-webhook", methods=["POST"])
def notion_webhook():
    data = request.get_json()
    # Step 1: Handle verification
    if data and "verification_token" in data:
        verification_token = data["verification_token"]
        print("Received Notion verification token:", verification_token)
        # You may want to store this token securely for future validation
        return "", 200

    # Step 2: Validate signature (recommended)
    signature = request.headers.get("X-Notion-Signature")
    if not signature:
        abort(400, "Missing Notion signature header")
    if not NOTION_VERIFICATION_TOKEN:
        abort(500, "Notion verification token not set in environment")
    calculated = (
        "sha256="
        + hmac.new(
            NOTION_VERIFICATION_TOKEN.encode(), request.data, hashlib.sha256
        ).hexdigest()
    )
    if not hmac.compare_digest(calculated, signature):
        abort(401, "Invalid signature")

    # Step 3: Handle the event payload
    print("Received Notion event:", data)
    # Do your processing here (e.g., update your DB, trigger actions, etc.)
    return jsonify({"received": True})


if __name__ == "__main__":
    app.run(debug=True)
