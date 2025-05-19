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
from src.notion.client import NotionClient
from src.llm.client import LLMClient

app = Flask(__name__)
app.secret_key = "your_very_secret_key_for_everything"

# Load environment variables from .env at the root of ./app
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
NOTION_API_KEY = os.getenv("NOTION_API_KEY")  # For webhook verification
NOTION_INTEGRATION_SECRET = os.getenv(
    "NOTION_INTERNAL_INTEGRATION_SECRET"
)  # For API interactions

if not NOTION_API_KEY:
    raise ValueError("NOTION_API_KEY environment variable is not set")
if not NOTION_INTEGRATION_SECRET:
    raise ValueError(
        "NOTION_INTERNAL_INTEGRATION_SECRET environment variable is not set"
    )

# Initialize Notion client with integration secret
notion_client = NotionClient(api_key=NOTION_INTEGRATION_SECRET)

# Initialize LLM Client
llm_client = LLMClient()

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
    if not data:
        abort(400, "Request body must be JSON")

    # Step 1: Handle verification (Notion might send this for webhook setup)
    if "challenge" in data:
        print("Received Notion verification challenge:", data["challenge"])
        return jsonify({"challenge": data["challenge"]})

    # Legacy verification (if still used, though challenge is more common now)
    if "verification_token" in data:
        print("Received Notion verification token:", data["verification_token"])
        return "", 200

    # Step 2: Validate signature (recommended)
    signature = request.headers.get("X-Notion-Signature-V2")  # V2 is common
    timestamp = request.headers.get("X-Notion-Request-Timestamp")

    if not signature or not timestamp:
        # Fallback to V1 if V2 headers are not present
        signature = request.headers.get("X-Notion-Signature")  # Original V1 header
        if not signature:
            print("Missing Notion signature header (V1 or V2)")
            abort(400, "Missing Notion signature header")
        # For V1, timestamp is not part of signature base string construction
        message = request.data
        secret = NOTION_API_KEY  # Webhook secret
    else:
        # V2 Signature
        message = f"{timestamp}:{request.data.decode('utf-8')}".encode("utf-8")
        secret = NOTION_API_KEY  # Webhook secret

    if not secret:
        print("Notion API key (webhook secret) not set in environment")
        abort(500, "Notion API key (webhook secret) not set in environment")

    calculated_signature = hmac.new(
        secret.encode(), message, hashlib.sha256
    ).hexdigest()

    # For V2, the signature header might look like "v1=actual_signature_hex"
    # For V1, it's just the hex string.
    actual_signature_to_compare = signature.split("=")[-1]

    if not hmac.compare_digest(calculated_signature, actual_signature_to_compare):
        print(
            f"Invalid signature. Calculated: {calculated_signature}, Received: {actual_signature_to_compare}"
        )
        abort(401, "Invalid signature")

    # Step 3: Handle the event payload
    print(
        "Received Notion event (after signature validation):",
        json.dumps(data, indent=2),
    )

    event_type = data.get("type")
    page_id = data.get("event", {}).get("id")  # Common structure for page events

    # For some events, page_id might be nested differently, e.g. inside 'data' or 'entity'
    if not page_id and data.get("entity"):  # From previous logs
        page_id = data.get("entity", {}).get("id")

    # If it's a page related event and we have a page_id
    if page_id and (
        event_type == "page.created"
        or event_type == "page.updated"
        or event_type == "page.content_updated"
        or "page" in data.get("entity", {}).get("type", "")
    ):
        print(f"Processing event for page_id: {page_id}")

        current_status = notion_client.get_page_status(page_id)
        print(f"Current 'Joko Bot - Status' for page {page_id}: {current_status}")

        if current_status == "Ready for analysis":
            print(
                f"Status is 'Ready for analysis'. Proceeding with processing for page {page_id}."
            )
            try:
                # 1. Update status to "In progress"
                notion_client.update_page_status(page_id, "In progress")
                print(f"Updated status to 'In progress' for page {page_id}.")

                # 2. Fetch page details and content
                page_details = notion_client.get_page(page_id)
                page_content_blocks = notion_client.get_page_content(page_id)
                page_markdown_content = notion_client.notion_blocks_to_markdown(
                    page_content_blocks
                )

                # Prepare properties for LLM (simple string representation)
                properties_for_llm = {
                    prop: str(val)
                    for prop, val in page_details.get("properties", {}).items()
                }

                # 3. Prepare LLM prompt
                system_prompt = f"""
Your task is to analyze the provided Notion page content and its properties to extract structured information about a merchant and their offers. 
Format your output as a JSON object conforming to the following schema. The source of information is the Notion page, not an email.

JSON Schema:
```json
{{
  "merchant": {{
    "name": "string (REQUIRED - The name of the merchant, e.g., 'SHEIN', 'New Local Bakery')",
    "additional_details": {{
      "about_text_from_notion_page": "string (Optional - Descriptive text about the merchant if found on the page)",
      "banner_img_url_from_notion_page": "string (Optional - URL for a banner image if found on the page)",
      "merchant_image_url_from_notion_page": "string (Optional - Logo URL if found on the page)",
      "merchant_days_hint_from_notion_page": "string (Optional - Textual hint for validation period if found on the page)"
    }}
  }},
  "offers": [
    {{
      "offer_value_statement_from_notion_page": "string (REQUIRED - The exact offer value as stated on the page, e.g., '7.5% cashback', '55 € bonus')",
      "additional_details": {{
        "offer_description_text_from_notion_page": "string (Optional - Description of the offer if found on the page)",
        "end_date_text_from_notion_page": "string (Optional - Offer expiry date as text if found on the page)",
        "imagined_cashback_code_text_from_notion_page": "string (Optional - Promo code if mentioned on the page)",
        "availability_hint_from_notion_page": "string (Optional - Text indicating if offer is not for immediate publishing if found on the page)",
        "conditions_list_text_from_notion_page": [
          "string (A list of individual conditions stated on the page)"
        ]
      }}
    }}
  ]
}}
```

Ensure the output is ONLY the JSON object, without any surrounding text or explanations.
"""
                user_content = f"Page Properties:\n{json.dumps(properties_for_llm, indent=2)}\n\nPage Content (Markdown):\n{page_markdown_content}"

                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ]

                print(f"Sending data to LLM for page {page_id}...")
                llm_response = llm_client.run_completion(
                    messages=messages,
                    model="gemini/gemini-2.5-flash-preview-04-17",  # Or your preferred model
                    response_format={"type": "json_object"},
                )

                if (
                    llm_response
                    and llm_response.choices
                    and llm_response.choices[0].message.content
                ):
                    extracted_json_str = llm_response.choices[0].message.content
                    print(f"LLM Response for page {page_id}:\n{extracted_json_str}")
                    try:
                        # Validate if it's proper JSON, though LLM should ensure this in JSON mode
                        parsed_json = json.loads(extracted_json_str)
                        # 4. Append LLM output to page
                        notion_client.append_code_block_to_page(
                            page_id, json.dumps(parsed_json, indent=2), language="json"
                        )
                        print(f"Appended LLM JSON to page {page_id}.")

                        # 5. Update status to "Done"
                        notion_client.update_page_status(page_id, "Done")
                        print(f"Updated status to 'Done' for page {page_id}.")
                    except json.JSONDecodeError as json_e:
                        print(
                            f"LLM output was not valid JSON for page {page_id}: {json_e}. Output:\n{extracted_json_str}"
                        )
                        # Optionally, update status to an error state here
                        notion_client.update_page_status(
                            page_id, "Error Processing"
                        )  # Example error status
                else:
                    print(f"LLM did not return expected content for page {page_id}.")
                    notion_client.update_page_status(
                        page_id, "Error Processing"
                    )  # Example error status

            except Exception as e:
                print(f"Error during processing for page {page_id}: {e}")
                if hasattr(e, "response") and e.response:
                    print(f"Error Response: {e.response.text}")
                # Attempt to set status to Error Processing if something went wrong
                try:
                    notion_client.update_page_status(page_id, "Error Processing")
                except Exception as e_status:
                    print(
                        f"Failed to update status to Error Processing for page {page_id}: {e_status}"
                    )
        elif current_status:
            print(
                f"Page {page_id} status is '{current_status}', not 'Ready for analysis'. Skipping."
            )
        else:
            print(
                f"Could not determine status for page {page_id} or status is not set. Skipping."
            )
    else:
        print("Event is not a page event or page_id is missing. Skipping processing.")
        # print(f"Debug: event_type: {event_type}, page_id: {page_id}, data.get('entity',{}).get('type', '"): {data.get('entity',{}).get('type', '')}")

    return jsonify(
        {"received": True, "processed_page_id": page_id if page_id else None}
    )


if __name__ == "__main__":
    app.run(debug=True)
