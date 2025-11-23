from kivy.lang import Builder
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDRaisedButton
from kivy.clock import mainthread
import threading
from ollama import chat
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
import re

KV = """
<RecipeAppLayout>:
    orientation: "vertical"
    spacing: 15
    padding: 20

    MDTextField:
        id: ingredient_input
        hint_text: "Enter ingredients (e.g. chicken, garlic, tomatoes)"
        size_hint_y: None
        height: "50dp"
        size_hint_x: None
        width: "700dp"
        pos_hint: {"center_x": 0.5}
        multiline: False

    MDRaisedButton:
        text: "Find Possible Foods"
        size_hint_y: None
        height: "50dp"
        pos_hint: {"center_x": 0.5}
        on_release: root.find_possible_foods()

    MDLabel:
        id: status_label
        text: "Possible foods will appear here."
        size_hint_y: None
        height: "30dp"
        theme_text_color: "Custom"
        markup: True
        halign: "center"

    ScrollView:
        size_hint_y: 0.3
        do_scroll_x: True     
        do_scroll_y: False 
        MDBoxLayout:
            orientation: "horizontal"
            id: foods_grid_container
            size_hint_y: None
            height: self.minimum_height
            spacing: 20
            padding: 10
            adaptive_size: True

    ScrollView:
        size_hint_y: 0.6
        MDBoxLayout:
            size_hint_y: None
            height: self.minimum_height
            orientation: "vertical"
            padding: 10
            MDLabel:
                id: recipe_label
                text: "Selected recipe will appear here."
                size_hint_y: None
                height: self.texture_size[1]
                text_size: self.width, None
                markup: True
           
                valign: "middle"

    MDRaisedButton:
        text: "Download Recipe as PDF"
        size_hint_y: None
        height: "90dp"
        pos_hint: {"center_x": 0.5}
        on_release: root.download_recipe_pdf()
"""

# -------------------------- Python Layout --------------------------
class RecipeAppLayout(MDBoxLayout):
    def find_possible_foods(self):
        ingredients = self.ids.ingredient_input.text.strip()
        if not ingredients:
            self.update_status("[color=ff0000]Please enter ingredients !!![/color]")
            return
        self.update_status("[color=00aa00]⏳ Finding possible foods...[/color]")
        self.ids.foods_grid_container.clear_widgets()
        self.ids.recipe_label.text = "Selected recipe will appear here."
        threading.Thread(
            target=self._ollama_generate_foods, args=(ingredients,), daemon=True
        ).start()

    def _ollama_generate_foods(self, ingredients):
        prompt = (
            f"You are a chef. From these ingredients: {ingredients}, "
            "provide a list of 5 possible dishes. Just provide the names separated by commas."
        )
        try:
            response = chat(
                model="gemma3",
                messages=[
                    {"role": "system", "content": "You are a professional chef."},
                    {"role": "user", "content": prompt},
                ],
            )
            dishes_text = response["message"]["content"]
            dishes = [d.strip() for d in dishes_text.replace("\n", ",").split(",") if d.strip()]
            self.update_foods_grid(dishes)
        except Exception as e:
            self.update_status(f"[color=ff0000]Error: {str(e)}[/color]")

    @mainthread
    def update_status(self, text):
        self.ids.status_label.text = text

    @mainthread
    def update_foods_grid(self, dishes):
        self.update_status("Select a dish to see the recipe:")
        self.ids.foods_grid_container.clear_widgets()
        for dish in dishes:
            btn = MDRaisedButton(
                text=dish,
                md_bg_color=(1, 0.5, 0, 1),  # orange
                size_hint=(None, None),
                size=(max(150, len(dish)*8), 50),  # width adapts to text length
                on_release=lambda inst, d=dish: self.get_recipe(d)
            )
            self.ids.foods_grid_container.add_widget(btn)

    def get_recipe(self, dish_name):
        self.update_status(f"⏳ Generating recipe for {dish_name}...")
        self.ids.recipe_label.text = "[color=00aa00][b]Loading recipe...[/b][/color]"
        threading.Thread(
            target=self._ollama_generate_recipe_stream, args=(dish_name,), daemon=True,
        ).start()

    # ---------------- STREAMING RECIPE GENERATOR ----------------
    def _ollama_generate_recipe_stream(self, dish_name):
        prompt = (
            f"Provide a recipe for {dish_name}. "
            "Format the response as:\n\n"
            "Title: Recipe Name\n"
            "Ingredients:\n- item 1\n- item 2\n\n"
            "Instructions:\n1. step 1\n2. step 2\n"
            "Do not include introduction or suggestion at the end."
        )
        try:
            combined_text = ""
            for chunk in chat(
                model="gemma3",
                messages=[
                    {"role": "system", "content": "You are a professional chef."},
                    {"role": "user", "content": prompt},
                ],
                stream=True,
            ):
                delta = chunk["message"]["content"]
                combined_text += delta
                self.update_recipe_partial(self.clean_recipe_text(combined_text))
            self.update_status("[color=00aa00]Recipe generated.[/color]")
        except Exception as e:
            self.update_recipe_partial(f"[color=ff0000]Error: {str(e)}[/color]")

    # ---------------- CLEAN RECIPE TEXT ----------------
    def clean_recipe_text(self, text):
        lines = text.split("\n")
        filtered = []
        keep = False
        unwanted_keywords = ["suggest", "tip", "note", "serving", "enjoy", "conclusion"]
        for line in lines:
            lower = line.lower().strip()
            if any(k in lower for k in ["title:", "ingredients:", "instructions:"]):
                keep = True
                filtered.append(line)
                continue
            if any(word in lower for word in unwanted_keywords):
                keep = False
            if keep and line.strip():
                filtered.append(line)
        return "\n".join(filtered)

    @mainthread
    def update_recipe_partial(self, text):
        self.ids.recipe_label.text = text
        self.ids.recipe_label.texture_update()
        self.ids.recipe_label.height = self.ids.recipe_label.texture_size[1]

    # ------------------- PDF DOWNLOAD BUTTON -------------------
    def download_recipe_pdf(self):
        recipe_content = self.ids.recipe_label.text.strip()
        if recipe_content.startswith("Selected recipe will appear here"):
            self.update_status("[color=ff0000]No recipe to download![/color]")
            return
        try:
            filename = "recipe.pdf"
            doc = SimpleDocTemplate(
                filename,
                pagesize=letter,
                leftMargin=0.75 * inch,
                rightMargin=0.75 * inch,
                topMargin=0.75 * inch,
                bottomMargin=0.75 * inch,
            )
            styleN = ParagraphStyle(
                name="RecipeStyle",
                fontName="Helvetica",
                fontSize=14,
                leading=20
            )
            clean_text = re.sub(r"\[.*?\]", "", recipe_content)
            story = [Paragraph(clean_text.replace("\n", "<br/>"), styleN)]
            doc.build(story)
            self.update_status(f"[color=00aa00]PDF saved as {filename}[/color]")
        except Exception as e:
            self.update_status(f"[color=ff0000]PDF Error: {str(e)}[/color]")


# -------------------------- Main App --------------------------
class AIRecipeApp(MDApp):
    def build(self):
        self.theme_cls.primary_palette = "DeepPurple"
        self.theme_cls.theme_style = "Light"
        Builder.load_string(KV)
        return RecipeAppLayout()


if __name__ == "__main__":
    AIRecipeApp().run()
