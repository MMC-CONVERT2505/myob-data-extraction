
import pandas as pd 

# MYOB AU tax code -> rate mapping
TAX_RATE_MAP = {
    "GST": 0.10,
    "CAP": 0.10,
    "GNR": 0.10,
    "GSTPAY": 0.10,
    "GSTREC": 0.10,
    "FRE": 0.00,
    "GSTFREE": 0.00,
    "FREE": 0.00,
    "EXP": 0.00,
    "N-T": 0.00,
    "NT": 0.00,
    "NONE": 0.00,
    "NO TAX": 0.00,
    "EXEMPT": 0.00,
    "ZERO": 0.00,
    "ITS": 0.00,
    "INP": 0.00,
}

def _strip_hyphen(val):
    return str(val).replace("-", "") if val else ""

class QBOConverter:
    @staticmethod
    def _format_date(date_str):
        """Convert ISO date to DD/MM/YYYY."""
        if not date_str:
            return ""
        try:
            if isinstance(date_str, str) and "T" in date_str:
                date_str = date_str.split("T")[0]

            if isinstance(date_str, str):
                parts = date_str.split("-")
                if len(parts) == 3:
                    return f"{parts[2]}/{parts[1]}/{parts[0]}"
            return date_str
        except Exception:
            return date_str

    @staticmethod
    def _to_float(val, default=0.0):
        try:
            if val is None or val == "":
                return default
            return float(val)
        except Exception:
            return default

    @staticmethod
    def _get_tax_rate(line):
        tax_code = (line.get("TaxCode") or {}).get("Code", "")
        return TAX_RATE_MAP.get(str(tax_code).strip().upper(), 0.0)

    @staticmethod
    def _get_tax_amount(line):
        """
        Get tax amount:
        1) Prefer strict data fields (TotalTax/TaxTotal/TaxAmount/RowTaxAmount or nested Tax)
        2) If missing, use tax code rate mapping (AU MYOB codes).
        """
        if not isinstance(line, dict):
            return 0.0

        tax = (
            line.get("TotalTax")
            or line.get("TaxTotal")
            or line.get("TaxAmount")
            or line.get("RowTaxAmount")
        )

        if tax is None and isinstance(line.get("Tax"), dict):
            tax = line.get("Tax", {}).get("Amount") or line.get("Tax", {}).get("Total")

        tax_val = QBOConverter._to_float(tax, None)
        if tax_val is not None:
            return tax_val

        tax_code = (line.get("TaxCode") or {}).get("Code")
        if tax_code:
            mapped_rate = TAX_RATE_MAP.get(str(tax_code).strip().upper())
            if mapped_rate is not None:
                base = QBOConverter._to_float(line.get("Total", 0), 0.0)
                if base:
                    return round(base * mapped_rate, 2)

        return 0.0

    @staticmethod
    def _calculate_tax_exclusive(line, total, is_tax_inclusive, is_item, qty, unit_price):
        """
        ITEM:
        - qty * unit_price (no change)

        SERVICE / PROFESSIONAL / MISC:
        - if inclusive → total / (1 + GST)
        """
        gst_rate = QBOConverter._get_tax_rate(line)

        # API Total = tax exclusive amount (both item & service lines)
        if is_tax_inclusive and gst_rate > 0:
            tax_exclusive = round(total / (1 + gst_rate), 2)
        else:
            tax_exclusive = total

        if is_tax_inclusive:
            tax_amount = round(total - tax_exclusive, 2)
        else:
            tax_amount = round(tax_exclusive * gst_rate, 2)

        return tax_exclusive, tax_amount

    @staticmethod
    def _map_global_tax_calc(mode: str) -> str:
        """
        Map MYOB GlobalTaxCalculation to QBO-compatible values:
        - TaxInclusive  -> TaxInclusive
        - TaxExclusive  -> TaxExcluded
        - else          -> NotApplicable
        """
        text = str(mode).strip().lower()
        if "inclusive" in text:
            return "TaxInclusive"
        if "exclusive" in text or "excluded" in text:
            return "TaxExcluded"
        return "NotApplicable"

    # ================= INVOICES =================
    @staticmethod
    def convert_invoices(invoices):
        """Convert REAL MYOB invoices to QBO format with line item support + GST handling."""
        qbo_records = []

        for inv in invoices:
            if not inv:
                continue

            lines = inv.get("Lines") or []
            customer = inv.get("Customer") or {}
            customer_name = customer.get("Name", "")
            inv_number = inv.get("Number", "")
            inv_date = QBOConverter._format_date(inv.get("Date", ""))
            due_date = QBOConverter._format_date(inv.get("DueDate", ""))

            tax_calc_mode_raw = inv.get("GlobalTaxCalculation", "TaxExclusive")
            tax_calc_mode = QBOConverter._map_global_tax_calc(tax_calc_mode_raw)
            is_tax_inclusive = (
                "inclusive" in str(tax_calc_mode_raw).lower()
                or "true" in str(inv.get("IsTaxInclusive", False)).lower()
            )

            currency_code = inv.get("CurrencyCode", "")
            exchange_rate = inv.get("ExchangeRate", "")

            if not lines:
                total_amount = QBOConverter._to_float(inv.get("TotalAmount", 0), 0.0)
                qbo_records.append(
                    {
                        "Type": "Invoice",
                        "Invoice Date": inv_date,
                        "Invoice No": inv_number,
                        "Due Date": due_date,
                        "Customer": customer_name,
                        "Amount": total_amount,
                        "Tax Amount": QBOConverter._to_float(inv.get("TotalTax", 0), 0.0),
                        "Balance Due": inv.get("BalanceDueAmount", 0),
                        "Currency Code": currency_code,
                        "Exchange Rate": exchange_rate,
                        "Global Tax calculation": tax_calc_mode,
                    }
                )
                continue

            _frt_inc = QBOConverter._to_float(inv.get("Freight") or inv.get("FreightAmount") or 0, 0.0)
            freight_excl = round(_frt_inc / 1.1, 2) if _frt_inc else 0.0

            for line in lines:
                if not line:
                    continue

                is_item = bool(line.get("Item"))
                total = QBOConverter._to_float(line.get("Total"), 0.0)
                qty = line.get("ShipQuantity") or line.get("Quantity") or 1
                unit_price = QBOConverter._to_float(line.get("UnitPrice"), 0.0)

                tax_exclusive, tax_amount = QBOConverter._calculate_tax_exclusive(
                    line,
                    total,
                    is_tax_inclusive,
                    is_item,
                    qty,
                    unit_price,
                )
                _line_gst = QBOConverter._get_tax_rate(line)
                total_tax = round((tax_exclusive + freight_excl) * _line_gst, 2) if _line_gst > 0 else tax_amount

                amount = tax_exclusive

                product_service = (
                    (line.get("Item") or {}).get("Number")
                    or (line.get("Item") or {}).get("Name")
                    or line.get("Description", "")
                )

                qbo_record = {
            
                    "Invoice Date": inv_date,
                    "Invoice No": inv_number,
                    "Due Date": QBOConverter._format_date( 
                        inv.get("Terms", {}).get("DueDate")
                    )
                    or due_date,
                    "Customer": customer_name,
                    "Global Tax calculation": tax_calc_mode,
                    "Product/Service": product_service,
                    "Product/Service Description": line.get("Description", ""),
                    #"Product/Service Amount: line.get(""),
                    "Product/Service Quantity": (line.get("ShipQuantity") or line.get("Quantity") or 0),
                    "Product/Service Unit Price": round(tax_exclusive / qty, 6) if qty else tax_exclusive,
                    #"Product/Service Tax Rate": (line.get("TaxCode") or {}).get("Code", ""),
                    "Product/Service Tax Rate": f"{int(QBOConverter._get_tax_rate(line) * 100)}%",
                    "Product/Service Amount": tax_exclusive,
                    "Product/Service Tax Code": (line.get("TaxCode") or {}).get("Code", ""),
                    "Product/Service Tax Amount": total_tax,
                    "Product/Service Class": (line.get("Job") or {}).get("Number", ""),
                    "Currency Code": currency_code,
                    "Exchange Rate": exchange_rate,
                    #"Amount": amount,
                    "Tax Exclusive Amount": tax_exclusive,
                    "Total Invoice Amount": inv.get("TotalAmount", 0),
                    #"Freight ($)": freight_excl,
                     
                } 
 
                qbo_records.append(qbo_record)

        return qbo_records

    # ================= BILLS =================
    @staticmethod
    def convert_bills(bills):
        """Convert REAL MYOB bills to QBO format with line item support."""
        qbo_records = []

        for bill in bills:
            if not bill:
                continue

            lines = bill.get("Lines") or []
            supplier = bill.get("Supplier") or {}
            supplier_name = supplier.get("Name", "")
            bill_number = bill.get("Number", "")
            bill_date = QBOConverter._format_date(bill.get("Date", ""))
            due_date = QBOConverter._format_date(bill.get("DueDate", ""))

            tax_calc_mode_raw = bill.get("GlobalTaxCalculation", "TaxExclusive")
            tax_calc_mode = QBOConverter._map_global_tax_calc(tax_calc_mode_raw)
            is_tax_inclusive = "inclusive" in str(tax_calc_mode_raw).lower()

            currency_code = bill.get("CurrencyCode", "")
            exchange_rate = bill.get("ExchangeRate", "")

            if not lines:
                total_amount = QBOConverter._to_float(bill.get("TotalAmount", 0), 0.0)
                qbo_records.append(
                    {
                        "Type": "Bill",
                        "Date": bill_date,
                        "Bill No": bill_number,
                        "Due Date": due_date,
                        "Supplier": supplier_name,
                        "Amount": total_amount,
                        "Tax Amount": QBOConverter._to_float(
                            bill.get("TotalTax", 0), 0.0
                        ),
                        "Balance Due": bill.get("BalanceDueAmount", 0),
                        "Global Tax calculation": tax_calc_mode,
                    }
                )
                continue

            _frt_inc = QBOConverter._to_float(bill.get("Freight") or bill.get("FreightAmount") or 0, 0.0)
            freight_excl = round(_frt_inc / 1.1, 2) if _frt_inc else 0.0

            for line in lines:
                if not line:
                    continue

                is_item = bool(line.get("Item"))
                total = QBOConverter._to_float(line.get("Total"), 0.0)
                qty = line.get("BillQuantity") or line.get("Quantity") or 1
                unit_price = QBOConverter._to_float(line.get("UnitPrice"), 0.0)

                tax_exclusive, tax_amount = QBOConverter._calculate_tax_exclusive(
                    line,
                    total,
                    is_tax_inclusive,
                    is_item,
                    qty,
                    unit_price,
                )
                _line_gst = QBOConverter._get_tax_rate(line)
                total_tax = round((tax_exclusive + freight_excl) * _line_gst, 2) if _line_gst > 0 else tax_amount

                amount = tax_exclusive

                qbo_record = {
                    
                    "Date": bill_date,
                    "Bill No": bill_number,
                    "Due Date": due_date,
                    "Supplier": supplier_name,
                    "Terms": bill.get("Terms", {}).get("Name", ""),
                    "Global Tax calculation": tax_calc_mode,
                    "Expense Account": _strip_hyphen(
                        (line.get("Account") or {}).get("DisplayID", "")
                        or (line.get("Account") or {}).get("Number", "")
                        or line.get("AccountNumber", "")),
                    "Expense Description": line.get("Description", ""),
                    "Expense Line Amount": tax_exclusive,
                    "Expense Class": (line.get("Job") or {}).get("Number", ""),
                    #"Expense Tax Code": (line.get("TaxCode") or {}).get("Code", ""),
                    "Expense Tax Code": f"{int(QBOConverter._get_tax_rate(line) * 100)}%",
                    "Expense Account Tax Amount": total_tax,
                    "Product/Service": ((line.get("Item") or {}).get("Name")or line.get("Description", "")),
                    "Product/Services Description": line.get("Description", ""),
                    "Product/Services Quantity": (line.get("BillQuantity") or line.get("Quantity") or 0),
                    #"Product/Services Tax Rate": (line.get("TaxCode") or {}).get("Code", ""),
                    "Product/Services Tax Rate": f"{int(QBOConverter._get_tax_rate(line) * 100)}%",
                    "Product/Service Amount": tax_exclusive,
                    "Product/Services Billable Status": line.get("BillableStatus", ""),
                    #"Product/Services Tax Code": (line.get("TaxCode") or {}).get("Code", ""),
                    "Product/Services Tax Code": f"{int(QBOConverter._get_tax_rate(line) * 100)}%",
                    "Product/Services Tax Amount": total_tax,
                    "Product/Services Markup Percent": line.get("MarkupPercent", 0),
                    "Billable Customer": line.get("BillableCustomer", ""),
                    "Product/Services Class": (line.get("Job") or {}).get("Number", ""),
                    "Location": '',
                    "Currency Code": currency_code,
                    "Exchange Rate": exchange_rate,
                    #"Unit Price": round(tax_exclusive / qty, 6) if qty else tax_exclusive,
                    #"Tax Rate": (line.get("TaxCode") or {}).get("Code", ""),
                    "Tax Exclusive Amount": tax_exclusive,
                    #"Amount": amount, 
                    #"Total Bill Amount": bill.get("TotalAmount", 0),
                    #"Freight ($)": freight_excl,
                }

                qbo_records.append(qbo_record)
 
        return qbo_records

    # ================= CREDITS =================
    @staticmethod
    def convert_credits(credits, type_label="Credit Note"):
        """Convert MYOB Credit Notes / Vendor Credits to QBO format — line item loop."""
        qbo_records = []

        for cred in credits:
            if not cred:
                continue

            contact_name = (
                (cred.get("Customer") or {}).get("Name", "")
                or (cred.get("Supplier") or {}).get("Name", "")
            )
            cred_number   = cred.get("Number", "")
            cred_date     = QBOConverter._format_date(cred.get("Date", ""))
            due_date      = QBOConverter._format_date(cred.get("DueDate", ""))
            total_amount  = QBOConverter._to_float(cred.get("TotalAmount"), 0.0)
            balance_due   = QBOConverter._to_float(cred.get("BalanceDueAmount"), 0.0)
            currency_code = cred.get("CurrencyCode", "")
            exchange_rate = cred.get("ExchangeRate", "")

            tax_calc_mode_raw = cred.get("IsTaxInclusive", False)
            is_tax_inclusive  = (
                tax_calc_mode_raw is True
                or str(tax_calc_mode_raw).lower() == "true"
                or "inclusive" in str(cred.get("GlobalTaxCalculation", "")).lower()
            )
            tax_calc_mode = QBOConverter._map_global_tax_calc(
                "TaxInclusive" if is_tax_inclusive else "TaxExclusive"
            )

            lines = cred.get("Lines") or []

            if not lines:
                qbo_records.append({
                    #"Type": type_label,
                    "Invoice Date": cred_date,
                    "Invoice No": cred_number,
                    "Due Date": due_date,
                    "Customer": contact_name,
                    "Global Tax calculation": tax_calc_mode,
                    "Product/Service": "",
                    "Product/Service Description": "",
                    "Product/Service Quantity": 0,
                    "Product/Service Unit Price": 0,
                    "Product/Service Tax Rate": (cred.get("TaxCode") or {}).get("Code", ""),
                    "Product/Service Tax Amount": QBOConverter._to_float(cred.get("TotalTax"), 0.0),
                    "Tax Amount": QBOConverter._to_float(cred.get("TotalTax"), 0.0),
                    "Product/Service Class": "",
                    "Currency Code": currency_code,
                    "Exchange Rate": exchange_rate,
                    "Amount": total_amount,
                    #"Tax Exclusive Amount": total_amount,
                    "Total Credit Amount": total_amount,
                    "Balance Due": balance_due,
                    #"Freight ($)": 0,
                })
                continue

            for line in lines:
                if not line:
                    continue

                is_item    = bool(line.get("Item"))
                total      = QBOConverter._to_float(line.get("Total"), 0.0)
                unit_price = QBOConverter._to_float(line.get("UnitPrice"), 0.0)
                qty = (line.get("ShipQuantity") or line.get("BillQuantity") or line.get("Quantity")
                       or (round(total / unit_price, 4) if unit_price else 1))

                tax_exclusive, tax_amount = QBOConverter._calculate_tax_exclusive(
                    line, total, is_tax_inclusive, is_item, qty, unit_price
                )

                product_service = (
                    (line.get("Item") or {}).get("Number")
                    or (line.get("Item") or {}).get("Name")
                    or line.get("Description", "")
                )

                qbo_records.append({
                    "Adjustment Note No": "",
                    "Invoice Date": cred_date, 
                    "Invoice No": cred_number,  
                     
                    "Customer": contact_name,
                    "Adjustment Note Date": "",
                    "Global Tax calculation": tax_calc_mode,          
                    "Product/Service": product_service,
                    "Product/Service Description": line.get("Description", ""),
                    "Product/Service Quantity": qty,   
                    "Product/Service Unit Price": unit_price,
                    "Product/Service Tax Rate": (line.get("TaxCode") or {}).get("Code", ""),
                    "Product/Service Tax Amount": tax_amount,
                    "Tax Amount": tax_amount,
                    "Product/Service Class": (line.get("Job") or {}).get("Number", ""),
                    "Currency Code": currency_code,
                    "Exchange Rate": exchange_rate,
                    "Location":"",
                    "Print Status": "",
                    "Email Status": "",
                    #"Amount": tax_exclusive, 
                    #"Tax Exclusive Amount": tax_exclusive,
                    #"Total Credit Amount": total_amount, 
                    #"Balance Due": balance_due,
                    #"Freight ($)": cred.get("Freight", 0) or cred.get("FreightAmount", 0) or 0,
                })

        return qbo_records

    # ================= PAYMENTS =================
    @staticmethod
    def convert_payments(payments, type_label="Payment"):
        
        qbo_records = []
 
        for p in payments:
            if not p:
                continue

            # ── Payment Date ──
            payment_date = QBOConverter._format_date(p.get("Date", ""))

            # ── Reference No ──
            # SupplierPayment → PaymentNumber | CustomerPayment → ReceiptNumber
            ref_no = (
                p.get("PaymentNumber")
                or p.get("ReceiptNumber")
                or p.get("ReferenceNumber")
                or ""
            )

            # ── Contact Name ──
            customer_name = (p.get("Customer") or {}).get("Name", "")
            supplier_name = (p.get("Supplier") or {}).get("Name", "")
            contact_name  = customer_name or supplier_name

            # ── Bank Account ──
            # Account is always nested: {"DisplayID": "2-2152", "Name": "Loan Caltech"}
            account      = p.get("Account") or {}
            account_id   = _strip_hyphen(account.get("DisplayID", ""))   # e.g. "2-2152"
            account_name = account.get("Name", "")         # e.g. "Loan Caltech Environment"
            bank_account = f"{account_id}  {account_name}".strip() if account_id else account_name

            # ── Memo ──
            memo = p.get("Memo", "")

            # ── Total Amount ──
            # SupplierPayment uses AmountPaid, CustomerPayment uses AmountReceived
            total_amount = QBOConverter._to_float(
                p.get("AmountPaid")
                or p.get("AmountReceived")
                or p.get("TotalAmount")
                or 0, 0.0
            )

            # ── Payment Lines ──
            # SupplierPayment → Lines[] with Purchase.Number
            # CustomerPayment → Invoices[] with Number
            lines    = p.get("Lines") or []
            invoices = p.get("Invoices") or []

            # Combine both (only one will have data)
            all_lines = lines + invoices

            # Dynamic column header — Bill No ya Invoice No
            doc_no_label = "Bill No" if "Supplier" in type_label else "Invoice No"

            if all_lines:
                for line in all_lines:
                    if not line:
                        continue

                    # SupplierPayment: line.Purchase.Number
                    # CustomerPayment: line.Number
                    purchase      = line.get("Purchase") or {}
                    bill_number   = purchase.get("Number", "") or line.get("Number", "")
                    line_type     = line.get("Type", "")   # "Bill" or "Invoice"
                    amount_applied = QBOConverter._to_float(
                        line.get("AmountApplied") or 0, 0.0
                    )

                    qbo_records.append({
                        
                        "Payment Date"       : payment_date,
                        "Reference No"       : ref_no,
                        "Journal No"         : ref_no,
                        
                        "Customer / Vendor"  : contact_name,
                        #"Account DisplayID"  : account_id,
                        "Account Name"       : account_name,
                        #"Bank Account"       : bank_account,
                        #"Description"        : memo,
                        doc_no_label         : bill_number,  
                        #"Line Type"          : line_type,
                        "Amount Applied ($)" : amount_applied,
                        "Total Amount Paid"  : total_amount,
                        "Payment Method"     : p.get("PaymentMethod", ""),
                        "Memo"               : memo,
                        "Currency Code"      : p.get("CurrencyCode", ""),
                        "Exchange Rate"      : p.get("ExchangeRate", "")
                    })
            else: 
                # No lines — single summary row
                qbo_records.append({
                    
                    "Payment Date"       : payment_date,
                    "Reference No"       : ref_no,
                    "Journal No"         : ref_no,
                    
                    "Customer / Vendor"  : contact_name, 
                    #"Account DisplayID"  : account_id,
                    "Account Name"       : account_name,  
                    #"Bank Account"       : bank_account,
                       
                    doc_no_label         : "",               
                    #"Line Type"          : "",  
                    "Amount " : total_amount,
                    "Total Amount Paid"  : total_amount,
                    #"Payment Method"     : p.get("PaymentMethod", ""),
                    "Memo"               : memo,
                    "Currency Code"      : p.get("CurrencyCode", ""),
                    "Exchange Rate"      : p.get("ExchangeRate", ""),
                })
 
        return qbo_records

       
 
    

# MYOB Tax Code → Xero Tax Rate Name

_MYOB_TO_XERO_TAX = {
    "GST":     "GST on Income",
    "GSTREC":  "GST on Income",
    "GNR":     "GST on Income",
    "CAP":     "GST on Expenses",
    "GSTPAY":  "GST on Expenses",
    "FRE":     "GST Free Income",
    "GSTFREE": "GST Free Income",
    "FREE":    "GST Free Income",
    "N-T":     "BAS Excluded",
    "NT":      "BAS Excluded",
    "NONE":    "BAS Excluded",
    "NO TAX":  "BAS Excluded",
    "EXEMPT":  "BAS Excluded",
    "ZERO":    "BAS Excluded",
    "EXP":     "BAS Excluded",
    "ITS":     "BAS Excluded",
    "INP":     "BAS Excluded",
    "IMPORT":  "GST on Imports",
    "IMPORTS": "GST on Imports",
}

def _xero_tax_type(code):
    return _MYOB_TO_XERO_TAX.get(str(code or "").strip().upper(), "BAS Excluded")


class XeroConverter:
    @staticmethod
    def convert_invoices(invoices):
        """Convert REAL MYOB invoices to Xero format."""
        xero_records = []

        for inv in invoices:
            if not inv:
                continue

            lines = inv.get("Lines") or []
            contact = inv.get("Customer") or {}

            if not lines:
                xero_record = {
                    "ContactName": contact.get("Name", ""),
                    "EmailAddress": contact.get("Email", ""),
                    "POAddressLine1": contact.get("Address", ""),
                    "POAddressLine2": "",
                    "POAddressLine3": "",
                    "POAddressLine4": "",
                    "POCity": contact.get("City", ""),
                    "PORegion": contact.get("State", ""),
                    "POPostalCode": contact.get("Postcode", ""),
                    "POCountry": contact.get("Country", ""),
                    "InvoiceNumber": inv.get("Number", ""),
                    "Reference": inv.get("PurchaseOrderNumber", ""),
                    "InvoiceDate": inv.get("Date", ""),
                    "DueDate": inv.get("DueDate", ""),
                    "Total": inv.get("TotalAmount", 0),
                    "InventoryItemCode": "",
                    "Description": "Invoice Summary",
                    "Quantity": 1,
                    "UnitAmount": inv.get("TotalAmount", 0),
                    "Discount": 0,
                    "AccountCode": "",
                    "TaxType": _xero_tax_type((inv.get("TaxCode") or {}).get("Code", "")),
                    "TaxAmount": inv.get("TotalTax", 0),
                    "TrackingName1": "",
                    "TrackingOption1": "",
                    "TrackingName2": "",
                    "TrackingOption2": "",
                    "Currency": inv.get("CurrencyCode", ""),
                    "BrandingTheme": "",
                }
                xero_records.append(xero_record)
                continue

            tax_calc_mode_raw = inv.get("GlobalTaxCalculation", "TaxExclusive")
            is_tax_inclusive = (
                "inclusive" in str(tax_calc_mode_raw).lower()
                or "true" in str(inv.get("IsTaxInclusive", False)).lower()
            )

            _frt_inc = QBOConverter._to_float(inv.get("Freight") or inv.get("FreightAmount") or 0, 0.0)
            freight_excl = round(_frt_inc / 1.1, 2) if _frt_inc else 0.0

            for line in lines:
                if not line:
                    continue

                is_item = bool(line.get("Item"))
                total = QBOConverter._to_float(line.get("Total"), 0.0)
                unit_price = QBOConverter._to_float(line.get("UnitPrice"), 0.0)
                qty = (line.get("ShipQuantity") or line.get("Quantity")
                       or (round(total / unit_price, 4) if unit_price else 1))

                tax_exclusive, tax_amount = QBOConverter._calculate_tax_exclusive(
                    line, total, is_tax_inclusive, is_item, qty, unit_price
                )
                _line_gst = QBOConverter._get_tax_rate(line)
                total_tax = round((tax_exclusive + freight_excl) * _line_gst, 2) if _line_gst > 0 else tax_amount

                xero_record = {
                    "ContactName": contact.get("Name", ""),
                    "EmailAddress": contact.get("Email", ""),
                    "POAddressLine1": contact.get("Address", ""),
                    "POAddressLine2": contact.get("AddressLine2", ""),
                    "POAddressLine3": contact.get("AddressLine3", ""),
                    "POAddressLine4": contact.get("AddressLine4", ""),
                    "POCity": contact.get("City", ""),
                    "PORegion": contact.get("State", ""),
                    "POPostalCode": contact.get("Postcode", ""),
                    "POCountry": contact.get("Country", ""),
                    "InvoiceNumber": inv.get("Number", ""),
                    "Reference": inv.get("PurchaseOrderNumber", ""),
                    "InvoiceDate": QBOConverter._format_date(inv.get("Date", "")),
                    "DueDate": QBOConverter._format_date((inv.get("Terms") or {}).get("DueDate") or inv.get("DueDate", "")),
                    "Total": inv.get("TotalAmount", 0),
                    "InventoryItemCode": (line.get("Item") or {}).get("Number", ""),
                    "Description": line.get("Description") or ".",
                    "Quantity": qty,
                    "UnitAmount": round(tax_exclusive / qty, 6) if qty else tax_exclusive,
                    "LineAmount": round(tax_exclusive, 2),
                    # "LineAmount": line.get("LineAmount", 0),
                    "Discount": line.get("Discount") or "",
                    "AccountCode": _strip_hyphen((line.get("Account") or {}).get("DisplayID", "") or (line.get("Account") or {}).get("Number", "")),
                    "TaxType": _xero_tax_type((line.get("TaxCode") or {}).get("Code", "")),
                    "TaxAmount": total_tax,
                    #"Tax Exclusive Amount": tax_exclusive,   
                    "TrackingName1": "",
                    "TrackingOption1": (line.get("") or {}).get("Number", ""),
                    "TrackingName2": "",
                    "TrackingOption2": "",
                    "Currency": inv.get("CurrencyCode", ""),
                    "BrandingTheme": "",
                    "LineAmountType": line.get("LineAmountType", "Tax Exclusive"),  
                    "Status":"Draft",                  
                    #"Freight ($)": inv.get("Freight", 0) or inv.get("FreightAmount", 0) or 0,
                }
    
                xero_records.append(xero_record)
  
        return xero_records
  
    @staticmethod
    def convert_bills(bills):
        """Convert REAL MYOB bills to Xero format."""
        xero_records = []

        for bill in bills:
            if not bill:
                continue

            lines = bill.get("Lines") or []
            supplier = bill.get("Supplier") or {}

            if not lines:
                xero_record = {
                    "ContactName": supplier.get("Name", ""),
                    "EmailAddress": supplier.get("Email", ""),
                    "POAddressLine1": supplier.get("Address", ""),
                    "POAddressLine2": "",
                    "POAddressLine3": "",
                    "POAddressLine4": "",
                    "POCity": supplier.get("City", ""),
                    "PORegion": supplier.get("State", ""),
                    "POPostalCode": supplier.get("Postcode", ""),
                    "POCountry": supplier.get("Country", ""),
                    "InvoiceNumber": bill.get("Number", ""),
                    "Reference": bill.get("SupplierInvoiceNumber", ""),
                    "Date": bill.get("Date", ""),
                    "DueDate": bill.get("DueDate", ""),
                    "Total": bill.get("TotalAmount", 0),
                    "InventoryItemCode": "",
                    "Description": "Bill Summary",
                    "Quantity": 1,
                    "UnitAmount": bill.get("TotalAmount", 0),
                    "Discount": 0,
                    "AccountCode": "",
                    "TaxType": _xero_tax_type((bill.get("TaxCode") or {}).get("Code", "")),
                    "TaxAmount": bill.get("TotalTax", 0),
                    "TrackingName1": "",
                    "TrackingOption1": "",
                    "TrackingName2": "",
                    "TrackingOption2": "",
                    "Currency": bill.get("CurrencyCode", ""),
                }
                xero_records.append(xero_record)
                continue

            tax_calc_mode_raw = bill.get("GlobalTaxCalculation", "TaxExclusive")
            is_tax_inclusive = "inclusive" in str(tax_calc_mode_raw).lower()

            _frt_inc = QBOConverter._to_float(bill.get("Freight") or bill.get("FreightAmount") or 0, 0.0)
            freight_excl = round(_frt_inc / 1.1, 2) if _frt_inc else 0.0

            for line in lines:
                if not line:
                    continue

                is_item = bool(line.get("Item"))
                total = QBOConverter._to_float(line.get("Total"), 0.0)
                unit_price = QBOConverter._to_float(line.get("UnitPrice"), 0.0)
                qty = (line.get("BillQuantity") or line.get("Quantity")
                       or (round(total / unit_price, 4) if unit_price else 1))

                tax_exclusive, tax_amount = QBOConverter._calculate_tax_exclusive(
                    line, total, is_tax_inclusive, is_item, qty, unit_price
                )
                _line_gst = QBOConverter._get_tax_rate(line)
                total_tax = round((tax_exclusive + freight_excl) * _line_gst, 2) if _line_gst > 0 else tax_amount

                xero_record = {
                    "ContactName": supplier.get("Name", ""),
                    "EmailAddress": supplier.get("Email", ""),
                    "POAddressLine1": supplier.get("Address", ""),
                    "POAddressLine2": supplier.get("AddressLine2", ""),
                    "POAddressLine3": supplier.get("AddressLine3", ""),
                    "POAddressLine4": supplier.get("AddressLine4", ""),
                    "POCity": supplier.get("City", ""),
                    "PORegion": supplier.get("State", ""),
                    "POPostalCode": supplier.get("Postcode", ""),
                    "POCountry": supplier.get("Country", ""),
                    "InvoiceNumber": bill.get("Number", ""),
                    #"Reference": bill.get("SupplierInvoiceNumber", ""),
                    "Invoice Date": QBOConverter._format_date(bill.get("Date", "")),
                    "Due Date": QBOConverter._format_date((bill.get("Terms") or {}).get("DueDate") or bill.get("DueDate", "")),
                    "Total": bill.get("TotalAmount", 0),
                    "InventoryItemCode": (line.get("Item") or {}).get("Number", ""),
                    "Description": line.get("Description") or ".",
                    "Quantity": qty,
                    "UnitAmount": round(tax_exclusive / qty, 6) if qty else tax_exclusive,
                    "LineAmount": round(tax_exclusive, 2),
                    #"Discount": line.get("Discount", 0),
                    #"LineAmount":line.get("LineAmount",""),
                    "AccountCode": _strip_hyphen((line.get("Account") or {}).get("DisplayID", "") or (line.get("Account") or {}).get("Number", "")),
                    "TaxType": _xero_tax_type((line.get("TaxCode") or {}).get("Code", "")),
                    "TaxAmount": total_tax,
                    #"Tax Exclusive Amount": tax_exclusive,
                    "TrackingName1": "",
                    "TrackingOption1": (line.get("") or {}).get("Number", ""),
                    "TrackingName2": "",
                    "TrackingOption2": "",
                    "Currency": bill.get("CurrencyCode", ""),
                    "Status": "Draft",
                    "LineAmountType": line.get("LineAmountType", ""),
                    #"Freight ($)": bill.get("Freight", 0) or bill.get("FreightAmount", 0) or 0,
                }     

                xero_records.append(xero_record)
 
        return xero_records

    @staticmethod
    def convert_credits(credits):
        """Convert REAL MYOB credits to Xero format."""
        xero_records = []

        for cred in credits:
            if not cred:
                continue

            lines = cred.get("Lines") or []
            contact = cred.get("Customer") or cred.get("Supplier") or {}

            if not lines:
                xero_record = {
                    "ContactName": contact.get("Name", ""),
                    "EmailAddress": contact.get("Email", ""),
                    "POAddressLine1": contact.get("Address", ""),
                    "POAddressLine2": "",
                    "POAddressLine3": "",
                    "POAddressLine4": "",
                    "POCity": contact.get("City", ""),
                    "PORegion": contact.get("State", ""),
                    "POPostalCode": contact.get("Postcode", ""),
                    "POCountry": contact.get("Country", ""),
                    "CreditNoteNumber": cred.get("Number", ""),
                    "Reference": cred.get("PurchaseOrderNumber", ""),
                    "Date": QBOConverter._format_date(cred.get("Date", "")),
                    "Total": cred.get("TotalAmount", 0),
                    "InventoryItemCode": "",
                    "Description": "Credit Note Summary",
                    "Quantity": 1,
                    "UnitAmount": cred.get("TotalAmount", 0),
                    "Discount": 0,
                    "AccountCode": "",
                    "TaxType": _xero_tax_type((cred.get("TaxCode") or {}).get("Code", "")),
                    "TaxAmount": cred.get("TotalTax", 0),
                    "TrackingName1": "",
                    "TrackingOption1": "",
                    "TrackingName2": "",
                    "TrackingOption2": "",
                    "Currency": cred.get("CurrencyCode", ""),
                }
                xero_records.append(xero_record)
                continue

            _is_tax_inc = (
                cred.get("IsTaxInclusive") is True
                or str(cred.get("IsTaxInclusive", "")).lower() == "true"
            )

            for line in lines:
                if not line:
                    continue

                _is_item    = bool(line.get("Item"))
                _total      = QBOConverter._to_float(line.get("Total"), 0.0)
                _unit_price = QBOConverter._to_float(line.get("UnitPrice"), 0.0)
                _qty = (line.get("ShipQuantity") or line.get("BillQuantity") or line.get("Quantity")
                        or (round(_total / _unit_price, 4) if _unit_price else 1))

                _tax_exclusive, _tax_amount = QBOConverter._calculate_tax_exclusive(
                    line, _total, _is_tax_inc, _is_item, _qty, _unit_price
                )

                xero_record = {
                    "ContactName": contact.get("Name", ""),
                    "EmailAddress": contact.get("Email", ""),
                    "POAddressLine1": contact.get("Address", ""),
                    "POAddressLine2": "",
                    "POAddressLine3": "",
                    "POAddressLine4": "",
                    "POCity": contact.get("City", ""),
                    "PORegion": contact.get("State", ""),
                    "POPostalCode": contact.get("Postcode", ""),
                    "POCountry": contact.get("Country", ""),
                    "InvoiceNumber": cred.get("InvoiceNumber", ""),
                    "CreditNoteNumber": cred.get("Number", ""),
                    "Reference": cred.get("PurchaseOrderNumber", ""),
                    "InvoiceDate": QBOConverter._format_date(cred.get("Date", "")),
                    "Total": cred.get("TotalAmount", 0),
                    "InventoryItemCode": (line.get("Item") or {}).get("Number", ""),
                    "Description": line.get("Description") or ".",
                    "Quantity": _qty,
                    "UnitAmount": _unit_price or _total or 0,
                    "LineAmount": _total,
                    "Discount": line.get("Discount") or "", 
                    "AccountCode": _strip_hyphen((line.get("Account") or {}).get("DisplayID", "") or (line.get("Account") or {}).get("Number", "")),
                    "TaxType": _xero_tax_type((line.get("TaxCode") or {}).get("Code", "")),
                    "TaxAmount": _tax_amount,
                    #"Tax Exclusive Amount": _tax_exclusive,
                    "TrackingName1": "",
                    "TrackingOption1": (line.get(" ") or {}).get("Number", ""),
                    "TrackingName2": "",
                    "TrackingOption2": "",
                    "Currency": cred.get("CurrencyCode", ""),
                    "BrandingTheme": "",
                    "LineAmountTypes": "",
                    "Status": "",
                }

                xero_records.append(xero_record)

        return xero_records

    @staticmethod
    def convert_payments(payments):
        """
        Convert MYOB CustomerPayment / SupplierPayment to Xero format.
        SupplierPayment → Lines[].Purchase.Number
        CustomerPayment → Invoices[].Number
        """
        xero_records = []

        for p in payments:
            if not p:
                continue

            payment_date = QBOConverter._format_date(p.get("Date", ""))

            # SupplierPayment → PaymentNumber | CustomerPayment → ReceiptNumber
            ref_no = (
                p.get("PaymentNumber")
                or p.get("ReceiptNumber")
                or p.get("ReferenceNumber")
                or ""
            )

            contact_name = (
                (p.get("Customer") or {}).get("Name", "")
                or (p.get("Supplier") or {}).get("Name", "")
            )

            account      = p.get("Account") or {}
            account_id   = _strip_hyphen(account.get("DisplayID", ""))
            account_name = account.get("Name", "")
            bank_account = f"{account_id} ".strip() if account_id else account_name

            memo = p.get("Memo", "")

            total_amount = QBOConverter._to_float(
                p.get("AmountPaid")
                or p.get("AmountReceived")
                or p.get("TotalAmount")
                or 0, 0.0
            )
 
            lines    = p.get("Lines") or []
            invoices = p.get("Invoices") or []
            all_lines = lines + invoices

            # Dynamic column header — BillNo ya InvoiceNo
            doc_no_label = "Bill No" if (p.get("Supplier") or p.get("PaymentNumber")) else "Invoice No"

            if all_lines:
                for line in all_lines:
                    if not line:
                        continue
 
                    purchase       = line.get("Purchase") or {}
                    bill_number    = purchase.get("Number", "") or line.get("Number", "")
                    line_type      = line.get("Type", "")
                    amount_applied = QBOConverter._to_float(line.get("AmountApplied") or 0, 0.0)
                   

                    xero_records.append({
                        #"ContactName"      : contact_name,
                        "Date"      : payment_date,                        
                        "Reference"        : ref_no,
                        #"AccountDisplayID" : account_id,
                        #"AccountName"      : account_name,
                        "Bank"      : bank_account,
                       # "Description"      : memo,
                        doc_no_label       : bill_number,    
                        "Amount"    : amount_applied,
                        "CurrencyRate" : '',
                       # "TotalAmountPaid"  : total_amount,
                    })  
            else: 
                xero_records.append({
                   # "ContactName"      : contact_name,
                    "PaymentDate"      : payment_date,
                    "Reference"        : ref_no,
                    #"AccountDisplayID" : account_id,
                    #"AccountName"      : account_name,
                    "Bank"      : bank_account,
                   # "Description"      : memo,
                    doc_no_label       : "",                 
                   # "LineType"         : "",  
                    "Amount"    : total_amount, 
                    "CurrencyRate" : '',
                    #"TotalAmountPaid"  : total_amount,
                })  

        return xero_records

 
class RawConverter: 
    @staticmethod
    def flatten_data(data):
        """
        Flatten MYOB JSON — har record ki Lines[] ko expand karo.
        Ek Bill mein 5 lines hain toh 5 rows banengi, header data repeat hoga.
        Agar Lines nahi hain toh 1 summary row.
        """
        all_rows = []

        for key in data:
            if not isinstance(data[key], list):
                continue

            for record in data[key]:
                if not record:
                    continue

                lines = record.get("Lines") or []

                if lines:
                    header = {k: v for k, v in record.items() if k != "Lines"}
                    for line in lines:
                        if not line:
                            continue
                        merged = {}
                        merged["_DataType"] = key
                        for hk, hv in header.items():
                            if isinstance(hv, dict):
                                for sk, sv in hv.items():
                                    merged[f"{hk}.{sk}"] = sv
                            elif isinstance(hv, list):
                                merged[hk] = str(hv)
                            else:
                                merged[hk] = hv
                        for lk, lv in line.items():
                            if isinstance(lv, dict):
                                for sk, sv in lv.items():
                                    merged[f"Line.{lk}.{sk}"] = sv
                            elif isinstance(lv, list):
                                merged[f"Line.{lk}"] = str(lv)
                            else:
                                merged[f"Line.{lk}"] = lv
                        all_rows.append(merged)
                else:
                    merged = {"_DataType": key}
                    for hk, hv in record.items():
                        if isinstance(hv, dict):
                            for sk, sv in hv.items():
                                merged[f"{hk}.{sk}"] = sv
                        elif isinstance(hv, list):
                            merged[hk] = str(hv)
                        else:
                            merged[hk] = hv
                    all_rows.append(merged)

        return all_rows

class ConverterFactory:
    @staticmethod
    def convert(data, data_type, format_type):
        """
        data: {
            "invoices": [...],
            "bills": [...],
            "credit_notes": [...],
            "vendor_credits": [...],
            "invoice_payments": [...],
            "bill_payments": [...],
            "customers": [...]
        }
        format_type: 'raw' | 'qbo' | 'xero'
        """
        if format_type == "raw":
            return RawConverter.flatten_data(data)

        if format_type == "qbo":
            converter = QBOConverter()
        else:
            converter = XeroConverter()

        all_records = []

        if "invoices" in data:
            all_records.extend(converter.convert_invoices(data["invoices"]))

        if "bills" in data:
            all_records.extend(converter.convert_bills(data["bills"]))

        if "credit_notes" in data and hasattr(converter, "convert_credits"):
            try:
                all_records.extend(
                    converter.convert_credits(data["credit_notes"], "Credit Note")
                )
            except TypeError:
                all_records.extend(converter.convert_credits(data["credit_notes"]))

        if "vendor_credits" in data and hasattr(converter, "convert_credits"):
            try:
                all_records.extend(
                    converter.convert_credits(data["vendor_credits"], "Vendor Credit")
                )
            except TypeError:
                all_records.extend(converter.convert_credits(data["vendor_credits"]))

        if "invoice_payments" in data and hasattr(converter, "convert_payments"):
            try:
                all_records.extend(
                    converter.convert_payments(
                        data["invoice_payments"], "Customer Payment"
                    )
                )
            except TypeError:
                all_records.extend(converter.convert_payments(data["invoice_payments"]))

        if "bill_payments" in data and hasattr(converter, "convert_payments"):
            try:
                all_records.extend(
                    converter.convert_payments(
                        data["bill_payments"], "Supplier Payment"
                    )
                )
            except TypeError:
                all_records.extend(converter.convert_payments(data["bill_payments"]))

        return all_records