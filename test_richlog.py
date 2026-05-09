from textual.app import App
from textual.widgets import RichLog

class TestApp(App):
    def compose(self):
        yield RichLog()

    def on_mount(self):
        log = self.query_one(RichLog)
        log.write("test line 1")
        log.write("[bold]test line 2[/bold]")
        self.set_timer(0.5, self.check_lines)
        
    def check_lines(self):
        log = self.query_one(RichLog)
        plain_lines = []
        for strip in log.lines:
            # text = strip.text  # rich 13.0 strip has .text
            if hasattr(strip, "text"):
                plain_lines.append(strip.text)
            else:
                plain_lines.append("".join(seg.text for seg in strip))
        
        with open("out.txt", "w") as f:
            f.write(f"Plain lines: {plain_lines}\n")
        self.exit()

TestApp().run()
