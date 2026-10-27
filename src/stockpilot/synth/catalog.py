"""Product categories of the fictional distributor.

Each category carries its yearly demand profile, sourcing mix and generic product types; each
product type has a plausible list-price band (THB per piece) and the pack sizes it ships in.
All values are invented configuration, not data from any real company.
"""

from __future__ import annotations

from dataclasses import dataclass

Product = tuple[str, float, float, tuple[int, ...]]  # name, min price, max price, units per box


@dataclass(frozen=True)
class Category:
    code: str
    name: str
    material_prefix: int  # first two digits of the 8-digit material number
    monthly_profile: tuple[float, ...]  # relative demand, January .. December
    import_share: float  # share of this category's suppliers located abroad
    promotable: bool  # takes part in trade promotions
    songkran_surge: bool  # extra orders before the Songkran holidays
    products: tuple[Product, ...]


# fmt: off
CATEGORIES: tuple[Category, ...] = (
    Category(
        "BEV", "Beverages", 10,
        (0.90, 0.95, 1.15, 1.30, 1.20, 1.00, 0.95, 0.90, 0.90, 0.90, 0.90, 0.95),
        0.0, True, True,
        (("Green Tea 500ml", 15, 25, (24,)), ("Lemon Soda 325ml", 12, 18, (24,)),
         ("Drinking Water 600ml", 6, 10, (12,)), ("Orange Juice 1L", 45, 75, (12,)),
         ("Energy Drink 150ml", 10, 14, (24, 50)), ("Canned Coffee 180ml", 13, 20, (24,)),
         ("Soy Milk 300ml", 10, 16, (24,)), ("Sparkling Water 330ml", 15, 25, (24,))),
    ),
    Category(
        "SNK", "Snacks & Confectionery", 11,
        (1.00, 1.00, 1.00, 1.05, 1.00, 0.95, 0.95, 0.95, 0.95, 1.00, 1.05, 1.10),
        0.1, True, True,
        (("Potato Chips 50g", 20, 30, (24,)), ("Rice Cracker 70g", 15, 25, (24,)),
         ("Chocolate Wafer 40g", 8, 15, (48,)), ("Peanut Snack 60g", 10, 20, (36,)),
         ("Butter Cookies 120g", 35, 60, (24,)), ("Gummy Candy 80g", 15, 30, (24,)),
         ("Seaweed Snack 32g", 25, 40, (36,))),
    ),
    Category(
        "GRO", "Dry Groceries", 12,
        (1.00, 0.98, 1.00, 1.02, 1.00, 0.98, 0.98, 0.98, 1.00, 1.00, 1.02, 1.04),
        0.05, True, False,
        (("Instant Noodles 60g", 5, 8, (30,)), ("Fish Sauce 700ml", 25, 45, (12,)),
         ("Jasmine Rice 5kg", 160, 260, (4,)), ("Cooking Oil 1L", 45, 65, (12,)),
         ("Canned Tuna 185g", 30, 45, (48,)), ("White Sugar 1kg", 22, 30, (25,)),
         ("Soy Sauce 300ml", 20, 35, (12,)), ("Coconut Milk 250ml", 15, 25, (24,))),
    ),
    Category(
        "PER", "Personal Care", 20,
        (1.00, 1.00, 1.05, 1.05, 1.00, 0.98, 0.98, 0.98, 0.98, 0.98, 1.00, 1.00),
        0.15, True, False,
        (("Shampoo 400ml", 90, 180, (12,)), ("Toothpaste 150g", 40, 90, (24,)),
         ("Bath Soap 75g", 12, 30, (48, 72)), ("Body Lotion 300ml", 80, 180, (12,)),
         ("Deodorant 50ml", 50, 110, (12,)), ("Facial Foam 100g", 60, 140, (24,)),
         ("Baby Powder 180g", 35, 60, (24,))),
    ),
    Category(
        "HOM", "Home Care", 21,
        (0.95, 0.92, 0.92, 0.95, 1.00, 1.05, 1.10, 1.10, 1.08, 1.03, 0.95, 0.95),
        0.1, True, False,
        (("Dish Soap 500ml", 20, 35, (12,)), ("Laundry Powder 1kg", 50, 90, (12,)),
         ("Floor Cleaner 800ml", 35, 60, (12,)), ("Fabric Softener 1L", 40, 70, (12,)),
         ("Insect Spray 600ml", 80, 130, (12,)), ("Toilet Cleaner 500ml", 30, 55, (12,)),
         ("Garbage Bags 30pcs", 25, 45, (24,))),
    ),
    Category(
        "STA", "Stationery & Office", 30,
        (0.85, 0.85, 1.00, 1.25, 1.45, 1.00, 0.90, 0.90, 0.95, 1.20, 0.95, 0.70),
        0.3, False, False,
        (("Ballpoint Pen Blue", 4, 10, (50,)), ("Notebook A5 80 Pages", 12, 25, (12, 24)),
         ("Copy Paper A4 500 Sheets", 95, 140, (5,)), ("Pencil HB 12pcs", 25, 50, (12,)),
         ("Glue Stick 21g", 15, 30, (12, 24)), ("Correction Tape", 20, 45, (12,)),
         ("Highlighter Set", 60, 120, (6, 12))),
    ),
    Category(
        "ELE", "Small Appliances", 40,
        (0.75, 0.95, 1.45, 1.70, 1.35, 0.90, 0.80, 0.75, 0.75, 0.75, 0.85, 1.00),
        0.6, False, False,
        (("Electric Fan 16in", 590, 1290, (1,)), ("Rice Cooker 1.8L", 690, 1590, (1,)),
         ("Electric Kettle 1.7L", 390, 890, (1, 2)), ("LED Bulb 9W", 45, 95, (10, 20)),
         ("Extension Cord 5m", 190, 450, (6, 10)), ("Steam Iron", 490, 1290, (1, 2)),
         ("Blender 1.5L", 690, 1690, (1,))),
    ),
    Category(
        "HWT", "Hardware & Tools", 41,
        (1.10, 1.10, 1.10, 1.00, 0.95, 0.90, 0.90, 0.90, 0.90, 1.00, 1.05, 1.10),
        0.5, False, False,
        (("Claw Hammer 16oz", 120, 290, (6, 12)), ("Screwdriver Set", 150, 390, (6, 12)),
         ("PVC Pipe 4m", 45, 120, (1,)), ("Wood Screws 100pcs", 35, 80, (10, 20)),
         ("Measuring Tape 5m", 80, 190, (12,)), ("Padlock 40mm", 90, 250, (6, 12)),
         ("Paint Brush 2in", 25, 60, (12,)), ("Cable Ties 100pcs", 30, 70, (20,))),
    ),
    Category(
        "GFT", "Gifts & Seasonal", 50,
        (1.30, 0.90, 0.70, 0.75, 0.70, 0.70, 0.70, 0.70, 0.80, 0.90, 1.40, 2.45),
        0.4, False, True,
        (("New Year Gift Basket", 590, 1990, (1,)), ("Festive Snack Box", 250, 690, (4, 6)),
         ("Tea Gift Set", 290, 890, (4, 6)), ("Juice Gift Set", 290, 690, (4, 6)),
         ("Cookie Tin 600g", 190, 390, (6, 12)), ("Dried Fruit Gift Box", 250, 590, (4, 6))),
    ),
)
# fmt: on

CATEGORY_INDEX = {c.code: i for i, c in enumerate(CATEGORIES)}

# P(category | demand pattern), in CATEGORIES order. Fast movers are mostly consumables; slow,
# lumpy movers are mostly durables, tools and gifts.
CATEGORY_GIVEN_PATTERN: dict[str, tuple[float, ...]] = {
    "smooth": (0.22, 0.18, 0.22, 0.16, 0.14, 0.05, 0.01, 0.01, 0.01),
    "erratic": (0.12, 0.12, 0.10, 0.12, 0.12, 0.17, 0.08, 0.07, 0.10),
    "intermittent": (0.03, 0.03, 0.05, 0.10, 0.08, 0.17, 0.20, 0.26, 0.08),
    "lumpy": (0.02, 0.02, 0.03, 0.06, 0.06, 0.14, 0.22, 0.27, 0.18),
}
