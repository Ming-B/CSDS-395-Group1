# JSON Tool — User Guide

## Save Progress vs. Save
- **Save Progress (Snapshot)**  
  Creates a *temporary snapshot* of your current work in the `/workspace` folder.  
  - Each snapshot records **both the data and your current view state** (expanded/collapsed nodes, cursor position).  
  - You can **undo/redo** to move between snapshots.  
  - Snapshots are cleared automatically when you close a file or exit the tool.

- **Save (File Overwrite)**  
  Writes your changes **directly to the original JSON file**.  
  - Use this when you are sure you want to replace the source file.  
  - This action is manual only (no shortcut) to avoid mistakes.

## Key Features
- **Automatic View Restore**  
  When you undo/redo, the tree will restore exactly where you were — expanded nodes, scroll position, and selected item.

- **Editable Keys and Values**  
  In the *Editor* tab, you can modify both the attribute names (keys) and their values.  
  - The tool ensures no duplicate keys in the same object.  
  - Different value types (string, number, boolean, null) are recognized automatically and displayed with color coding.



