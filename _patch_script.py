import sys
filepath = r"C:/Users/nikop/Desktop/MyStrow/App/main_window.py"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()
sm1 = "        def _rebuild_fd():"
sm2 = "            " + chr(34)*3 + "Reconstruit fixture_data depuis self.projectors" + chr(34)*3
start_marker = sm1 + chr(10) + sm2
em1 = "        dialog.exec()"
em2 = "        canvas_timer.stop()"
end_marker = em1 + chr(10) + em2
start_pos = content.find(start_marker)
if start_pos == -1:
    print("ERROR: start_marker not found"); sys.exit(1)
end_pos_full = content.find(end_marker)
if end_pos_full == -1:
    print("ERROR: end_marker not found"); sys.exit(1)
end_pos = end_pos_full + len(em1)
print(f"start_pos={start_pos} end_pos={end_pos} replacing={end_pos-start_pos} chars")
with open(r"C:/Users/nikop/Desktop/MyStrow/App/_replacement.py", "r", encoding="utf-8") as f:
    replacement = f.read()
new_content = content[:start_pos] + replacement + content[end_pos:]
with open(filepath, "w", encoding="utf-8") as f:
    f.write(new_content)
print("File written successfully.")
