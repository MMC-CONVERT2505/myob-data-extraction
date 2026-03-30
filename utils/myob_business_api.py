
import requests
import uuid
from urllib.parse import urlencode
from config import Config
 

class MYOBBusinessAPI:

    def __init__(self, access_token=None, business_id=None):
        self.access_token = access_token
        self.business_id = business_id

    # -------------------------
    # AUTH URL 
    # -------------------------
    @staticmethod
    def get_auth_url(state):
        params = {
            'client_id': Config.MYOB_CLIENT_ID,
            'redirect_uri': Config.MYOB_REDIRECT_URI,
            'response_type': 'code',
            'scope': Config.MYOB_SCOPES,
            'prompt': 'consent',
            'state': state or str(uuid.uuid4())
        }
        return f"{Config.MYOB_AUTH_URL}?{urlencode(params)}"

    # -------------------------
    # TOKEN EXCHANGE
    # -------------------------
    
    @staticmethod
    def exchange_code_for_token(code):
        data = {
            'client_id': Config.MYOB_CLIENT_ID,
            'client_secret': Config.MYOB_CLIENT_SECRET,
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': Config.MYOB_REDIRECT_URI
        }
        res = requests.post(
            Config.MYOB_TOKEN_URL,
            data=data,
            headers={'Content-Type': 'application/x-www-form-urlencoded'}
        )
        if res.status_code != 200:
            print("TOKEN ERROR:", res.text)
            return None
        return res.json()
 
    # -------------------------
    # REFRESH TOKEN
    # -------------------------

    @staticmethod
    def refresh_token(refresh_token):
        data = {
            'client_id': Config.MYOB_CLIENT_ID,
            'client_secret': Config.MYOB_CLIENT_SECRET,
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token
        }
        res = requests.post(
            Config.MYOB_TOKEN_URL,
            data=data,
            headers={'Content-Type': 'application/x-www-form-urlencoded'}
        )
        if res.status_code != 200:
            print("REFRESH ERROR:", res.text)
            return None
        return res.json()

    # -------------------------
    # HEADERS
    # -------------------------
    def _headers(self):
        return {
            'Authorization': f'Bearer {self.access_token}',
            'x-myobapi-key': Config.MYOB_CLIENT_ID,
            'x-myobapi-version': 'v2'
        }

    # -------------------------
    # DATA APIs 
    # -------------------------

    # --- Invoices ---
    def get_invoices(self, invoice_type='Item', start_date=None, end_date=None):
        url = f"https://api.myob.com/accountright/{self.business_id}/Sale/Invoice/{invoice_type}"
        params = self._build_date_filter(start_date, end_date)
        return self._get(url, params=params)


    # --- Credit Notes (Invoices with negative TotalAmount) ---
    def get_credit_notes(self, start_date=None, end_date=None):
        """
        Credit notes are derived from sales invoices by filtering rows
        where TotalAmount is negative.
        """
        all_items = []
        invoice_types = ['Item', 'Service', 'Professional', 'TimeBilling', 'Miscellaneous']

        for inv_type in invoice_types:
            url = f"https://api.myob.com/accountright/{self.business_id}/Sale/Invoice/{inv_type}"
            params = self._build_date_filter(start_date, end_date)
            res = self._get(url, params=params)

            if not res or 'Items' not in res:
                continue

            for item in res['Items']:
                total = item.get('TotalAmount', 0)
                try:
                    total_value = float(total)
                except (TypeError, ValueError):
                    continue

                if total_value < 0:
                    item['_source_invoice_type'] = inv_type
                    all_items.append(item)

        return {'Items': all_items}

    # --- Credit Settlements ---
    def get_credit_settlements(self, start_date=None, end_date=None):
        url = f"https://api.myob.com/accountright/{self.business_id}/Sale/CreditSettlement"
        params = self._build_date_filter(start_date, end_date)
        return self._get(url, params=params)

    # --- Bills ---
    def get_bills(self, bill_type='Item', start_date=None, end_date=None):
        url = f"https://api.myob.com/accountright/{self.business_id}/Purchase/Bill/{bill_type}"
        params = self._build_date_filter(start_date, end_date)
        return self._get(url, params=params)

    def get_vendor_credits(self, start_date=None, end_date=None):
        
        all_items = []
        for bill_type in ['Item', 'Service', 'Professional', 'Miscellaneous']:
            url = f"https://api.myob.com/accountright/{self.business_id}/Purchase/Bill/{bill_type}"
            params = self._build_date_filter(start_date, end_date)
            res = self._get(url, params=params)
            if res and 'Items' in res:
                credit_items = [
                    item for item in res['Items']
                    if float(item.get('TotalAmount', 0) or 0) < 0  
                ]
                all_items.extend(credit_items)
        return {'Items': all_items}

    # --- Debit Settlements ---
    def get_debit_settlements(self, start_date=None, end_date=None):
        url = f"https://api.myob.com/accountright/{self.business_id}/Purchase/DebitSettlement"
        params = self._build_date_filter(start_date, end_date)
        return self._get(url, params=params)

    # --- Customer Payments (NO date filter) ---
    def get_invoice_payments(self, start_date=None, end_date=None):
        url = f"https://api.myob.com/accountright/{self.business_id}/Sale/CustomerPayment"
        params = self._build_date_filter(start_date, end_date)
        return self._get(url, params=params)

    # --- Supplier Payments (NO date filter) ---
    def get_bill_payments(self, start_date=None, end_date=None):
        url = f"https://api.myob.com/accountright/{self.business_id}/Purchase/SupplierPayment"
        params = self._build_date_filter(start_date, end_date)
        return self._get(url, params=params)

    # -------------------------
    # HELPERS 
    # -------------------------
    def _build_date_filter(self, start_date, end_date):
        """OData date filter — used for Invoice/Bill/Credit endpoints only"""
        params = {}
        filters = []
        if start_date:
            filters.append(f"Date ge datetime'{start_date}T00:00:00'")
        if end_date:
            filters.append(f"Date le datetime'{end_date}T23:59:59'")
        if filters:
            params['$filter'] = " and ".join(filters)
        return params

    def _get(self, url, params=None):
        """
        GET request with automatic pagination.
        MYOB default page = 400 records.
        Agar NextPageLink hai toh saari pages fetch karo.
        """
        print(f"GET {url} | params={params}")
        all_items = []

        # First request
        r = requests.get(url, headers=self._headers(), params=params)
        if r.status_code != 200:
            print(f"API ERROR ({r.status_code}): {r.text[:300]}")
            return None

        data = r.json()

        # Items collect karo
        if 'Items' in data:
            all_items.extend(data['Items'])
        else:
            # Non-list response (e.g. single object) seedha return karo
            return data

        # ✅ Pagination — NextPageLink follow karo jab tak exist kare
        next_link = data.get('NextPageLink')
        page_num = 2
        while next_link:
            print(f"  → Fetching page {page_num}: {next_link}")
            r = requests.get(next_link, headers=self._headers())
            if r.status_code != 200:
                print(f"  Pagination ERROR ({r.status_code}): {r.text[:200]}")
                break
            page_data = r.json()
            if 'Items' in page_data:
                all_items.extend(page_data['Items'])
            next_link = page_data.get('NextPageLink')
            page_num += 1   

        print(f"  Total records fetched: {len(all_items)}")
        data['Items'] = all_items
        return data

