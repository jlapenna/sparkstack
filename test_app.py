from textual.app import App
from textual.widgets import DataTable

class TestApp(App):
    def compose(self):
        yield DataTable()

    def on_mount(self):
        t = self.query_one(DataTable)
        t.add_column("A", key="A")
        t.add_row("[bold cyan]test[/]", key="r1")
        try:
            row_data = t.get_row_at(t.cursor_row)
            
            plain_text_parts = []
            for cell in row_data:
                if isinstance(cell, str):
                    from rich.text import Text
                    plain_text_parts.append(Text.from_markup(cell).plain)
                elif hasattr(cell, "plain"):
                    plain_text_parts.append(cell.plain)
                else:
                    plain_text_parts.append(str(cell))
            
            with open("out.txt", "w") as f:
                f.write(f"Row data: {plain_text_parts}\n")
        except Exception as e:
            with open("out.txt", "w") as f:
                f.write(f"Error: {e}\n")
        self.exit()

TestApp().run()
