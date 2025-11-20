{
    "name": "Fuel Management System",
    "summary": """FMS""",
    "description": """
        Long description of module's purpose
    """,
    "author": "Wanaag Solutions",
    "website": "https://github.com/mohamed-wanaag",
    "category": "Uncategorized",
    "version": "19.0.1.0.0",
    "depends": ["sale", "hr_expense", "stock", "sale_stock", "account", "purchase"],
    "application": True,
    "license": "LGPL-3",
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/data.xml",
        "wizards/wizards.xml",
        "reports/reports.xml",
        "reports/daily_summary.xml",
        "views/report.xml",
        "views/invoice_template.xml",
        "views/station.xml",
        "views/shift.xml",
        "views/sales_order_report.xml",
        "views/views.xml",
        "views/menus.xml",
    ],
}
