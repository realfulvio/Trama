# Confidence ellipses by group

In **Scatter / confidence ellipse**, choose the X and Y columns and enable an overlay. The overlay can use the scatter groups, all complete XY pairs together, or a separate grouping column. A data ellipse describes scatter, while the confidence region of the mean describes uncertainty about its center.

For grouped overlays, choose **By group** for the fill, the border or both on **Fill and border**. Open **Edit group styles…** and select the group to edit. You can set its fill color and opacity, and its border color, opacity, width and pattern. Clear any field to restore the graph setting for that group. Opacity zero hides that part of the contour. The editor's **Cancel** button discards its edits.

Save the project to retain the overrides. Trama stores them with the grouping column and the underlying value, so numeric `1` and text `"1"` have separate styles. Changes to source values still recalculate each contour. The per-group settings apply whenever the corresponding fill or border is set to **By group**.

In the Qt analysis dialog, open **Options → Edit group styles…** after choosing a grouping column and **By group** for the fill or border. Choose the group by its displayed value. Changing groups keeps your edits in the open dialog. **OK** returns them to the analysis and **Run** confirms them. Cancelling either dialog discards its pending edits.
