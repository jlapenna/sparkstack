from textual.widgets import DataTable

d = DataTable()
d.add_column("A", key="col_a")
d.add_row("1", key="row_1")

print("hasattr cursor_coordinate:", hasattr(d, "cursor_coordinate"))
print("hasattr get_row:", hasattr(d, "get_row"))
print("hasattr get_row_at:", hasattr(d, "get_row_at"))
print("hasattr cursor_row:", hasattr(d, "cursor_row"))
