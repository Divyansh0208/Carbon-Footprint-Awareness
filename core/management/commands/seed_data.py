"""
Seeds the database with starter data:
- EmissionFactor: approximate DEFRA (UK) / EPA (US) style factors. These are
  reasonable MVP approximations, NOT audited figures — replace with sourced,
  region-specific data before any production/public use.
- EducationContent + GlossaryTerm: human-written static content (no LLM).
- Recommendation: static action list per category.

Run with: python manage.py seed_data
"""
from django.core.management.base import BaseCommand
from core.models import EmissionFactor, EducationContent, GlossaryTerm, Recommendation


EMISSION_FACTORS = [
    # category, subcategory, label, unit, kg_co2_per_unit
    ("transport", "car_petrol", "Petrol car", "km", 0.192),
    ("transport", "car_diesel", "Diesel car", "km", 0.171),
    ("transport", "car_electric", "Electric car", "km", 0.053),
    ("transport", "bus", "Bus", "km", 0.105),
    ("transport", "train", "Train", "km", 0.041),
    ("transport", "flight_short", "Short-haul flight", "km", 0.255),
    ("transport", "flight_long", "Long-haul flight", "km", 0.195),
    ("transport", "motorbike", "Motorbike", "km", 0.114),

    ("energy", "electricity", "Electricity (grid avg)", "kWh", 0.233),
    ("energy", "natural_gas", "Natural gas (heating)", "kWh", 0.184),
    ("energy", "lpg", "LPG", "kWh", 0.214),

    ("food", "beef", "Beef", "kg", 27.0),
    ("food", "lamb", "Lamb", "kg", 21.0),
    ("food", "pork", "Pork", "kg", 7.6),
    ("food", "chicken", "Chicken", "kg", 6.1),
    ("food", "fish", "Fish (farmed avg)", "kg", 5.4),
    ("food", "dairy", "Dairy (milk)", "litre", 1.3),
    ("food", "vegetables", "Vegetables (avg)", "kg", 0.4),
    ("food", "rice", "Rice", "kg", 2.7),

    ("goods", "clothing_item", "New clothing item", "item", 10.0),
    ("goods", "electronics_small", "Small electronics item", "item", 50.0),
    ("goods", "plastic_packaging", "Plastic packaging", "kg", 6.0),
    ("goods", "paper", "Paper/cardboard", "kg", 1.1),
]

EDUCATION_CONTENT = [
    ("transport", "Why transport matters",
     "Transport is one of the largest sources of personal carbon emissions in most "
     "countries, driven mainly by car travel and flying. Switching even a portion of "
     "car trips to public transport, cycling, or walking can meaningfully cut your footprint.",
     "A single short-haul flight can emit more CO2 than months of average car commuting."),
    ("energy", "Understanding home energy emissions",
     "Heating, cooling, and electricity use in your home are major contributors to your "
     "footprint. The emissions depend heavily on how your local grid generates electricity "
     "and what fuel your heating system uses.",
     "Switching to a renewable electricity tariff can cut your home energy emissions dramatically "
     "without changing your usage habits."),
    ("food", "The carbon cost of food",
     "Food emissions vary enormously by type. Red meat (beef, lamb) has a far higher "
     "footprint than poultry, fish, or plant-based foods, mainly due to land use and methane "
     "from livestock digestion.",
     "Beef has roughly 4x the carbon footprint of chicken per kilogram."),
    ("goods", "Why 'stuff' has a footprint too",
     "Every manufactured item carries embedded emissions from raw material extraction, "
     "manufacturing, and transport. Buying less, buying durable, and choosing secondhand "
     "all reduce this 'embodied carbon.'",
     "Extending a garment's life by just 9 months can reduce its carbon, water, and waste footprint by around 20-30%."),
]

GLOSSARY_TERMS = [
    ("Carbon footprint", "The total amount of greenhouse gases (expressed as CO2 equivalent) produced directly and indirectly by an individual, organization, or activity."),
    ("CO2e (CO2 equivalent)", "A standard unit that expresses the impact of different greenhouse gases in terms of the equivalent amount of CO2."),
    ("Scope 1, 2, 3 emissions", "A framework used mainly in organizational accounting: Scope 1 is direct emissions, Scope 2 is emissions from purchased energy, Scope 3 is all other indirect emissions in a value chain."),
    ("Emission factor", "A value that converts an activity (like driving 1 km or eating 1 kg of beef) into an estimated amount of CO2e emitted."),
    ("Net zero", "A state where the greenhouse gases added to the atmosphere are balanced by an equivalent amount removed."),
    ("Embodied carbon", "The emissions associated with producing and transporting a product, as opposed to emissions from using it."),
]

RECOMMENDATIONS = [
    ("transport", "Replace one car commute per week with public transport or cycling.", 8.0, "low"),
    ("transport", "Combine multiple errands into a single car trip.", 4.0, "low"),
    ("transport", "Consider an electric or hybrid vehicle for your next car.", 50.0, "high"),
    ("transport", "Choose train over short-haul flights where possible.", 100.0, "med"),

    ("energy", "Switch to a renewable/green electricity tariff if available.", 60.0, "med"),
    ("energy", "Lower your thermostat by 1-2°C in winter.", 15.0, "low"),
    ("energy", "Improve home insulation.", 40.0, "high"),

    ("food", "Replace 2 beef meals per week with chicken or plant-based alternatives.", 18.0, "low"),
    ("food", "Reduce food waste by planning meals ahead.", 10.0, "low"),
    ("food", "Try one plant-based day per week.", 12.0, "low"),

    ("goods", "Buy secondhand clothing instead of new where possible.", 5.0, "low"),
    ("goods", "Repair electronics instead of replacing them.", 15.0, "med"),
    ("goods", "Choose products with minimal packaging.", 3.0, "low"),
]


class Command(BaseCommand):
    help = "Seed starter data: emission factors, education content, glossary, recommendations."

    def handle(self, *args, **options):
        created_count = 0
        for category, subcategory, label, unit, factor in EMISSION_FACTORS:
            obj, created = EmissionFactor.objects.update_or_create(
                category=category, subcategory=subcategory,
                defaults={"label": label, "unit": unit, "kg_co2_per_unit": factor}
            )
            created_count += created
        self.stdout.write(self.style.SUCCESS(f"EmissionFactor: {len(EMISSION_FACTORS)} processed ({created_count} new)"))

        created_count = 0
        for category, title, body, fun_fact in EDUCATION_CONTENT:
            obj, created = EducationContent.objects.update_or_create(
                title=title, defaults={"category": category, "body": body, "fun_fact": fun_fact}
            )
            created_count += created
        self.stdout.write(self.style.SUCCESS(f"EducationContent: {len(EDUCATION_CONTENT)} processed ({created_count} new)"))

        created_count = 0
        for term, definition in GLOSSARY_TERMS:
            obj, created = GlossaryTerm.objects.update_or_create(
                term=term, defaults={"definition": definition}
            )
            created_count += created
        self.stdout.write(self.style.SUCCESS(f"GlossaryTerm: {len(GLOSSARY_TERMS)} processed ({created_count} new)"))

        created_count = 0
        for category, action, saving, effort in RECOMMENDATIONS:
            obj, created = Recommendation.objects.get_or_create(
                category=category, action=action,
                defaults={"potential_saving_kg": saving, "effort": effort}
            )
            created_count += created
        self.stdout.write(self.style.SUCCESS(f"Recommendation: {len(RECOMMENDATIONS)} processed ({created_count} new)"))

        self.stdout.write(self.style.SUCCESS("Seeding complete."))
