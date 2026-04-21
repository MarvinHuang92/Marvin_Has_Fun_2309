**linear_interpolate_2d.py 函数与行为说明**

本文档总结 `linear_interpolate_2d.py` 中主要函数的行为、输入输出和异常情况，供快速查阅。

**`linear_interpolate(y_array, z_array, y_input)`**:
- **作用**: 对一维数据按 y 轴做线性插值/外推。
- **输入**: `y_array`、`z_array`（长度相同，至少 2），`y_input`（查询点）。
- **行为**:
  - 将 (y,z) 对按 y 升序排序。
  - 合并重复的 y：若重复 y 对应的 z 全相等则去重；若存在不一致值则抛 `ValueError`。
  - 若 `y_input` 精确命中某一 y，则返回对应 z。
  - 若在区间外，则使用两端最近点线性外推。
  - 否则在线段内按比例插值并返回浮点值。
- **异常**: 当输入长度不匹配或长度 < 2 时抛 `ValueError`；重复 y 对应不同 z 时抛 `ValueError`。

**`linear_interpolate_2d(x_array, y_array, z_array, x_input, y_input)`**:
- **作用**: 在规则矩阵网格上进行二维（双线性）插值；在 nx==1 时降级为沿 y 的一维插值。
- **输入**:
  - `x_array`: x 方向坐标序列（长度 nx，可含重复但需一致性）；
  - `y_array`: y 方向坐标序列（长度 ny，要求 ny >= 2）；
  - `z_array`: 可为扁平列表（长度 nx*ny），或为长度为 nx 的可迭代，每项为长度 ny 的行（表示每个 x 对应的 y 列值）；
  - `x_input`, `y_input`: 查询点（当 nx==1 时 `x_input` 被忽略）。
  
  物理量含义（模块中使用）：
  - `x`: time gap，单位 秒（time gap, sec）
  - `y`: ego vehicle speed，单位 m/s（ego vehicle speed, m/s）
  - `z`: desired following distance，单位 米（desired following distance, meter）
- **主要处理流程**:
  1. 规范化 `z_array` 为 shape `(nx, ny)` 的二维列表（按 x 为行、y 为列）。
  2. 先按 y 排序并对列重排；对重复 y 执行去重：若同一组重复列在每个 x 上的 z 值都相等，则合并为一列，否则抛 `ValueError`（“Duplicate y with conflicting z column values”）。
  3. 再按 x 排序并对行重排；对重复 x 执行去重：若同一组重复行在每列上的 z 值都相等，则合并为一行，否则抛 `ValueError`（“Duplicate x with conflicting z row values”）。
  4. 若去重后 `nx == 1`，记录日志并降级调用 `linear_interpolate(ys, zs_row, y_input)`（忽略 `x_input`）。
  5. 否则执行双线性插值：若查询点恰好命中网格节点（x,y 都存在于去重并排序后的坐标中），函数将直接返回该节点的 z 值作为快速返回；否则定位包含点的两个相邻 x 与两个相邻 y，先沿 y 在 x0/x1 处插值，再沿 x 做线性组合，返回浮点值；对边界情况支持外推。
- **异常**: 当 `y_array` 长度 < 2 或 `z_array` 大小与期望不符时抛 `ValueError`；遇到重复坐标但对应 z 值不一致时抛 `ValueError`。

**`_parse_array_input(s, default)`**:
- **作用**: 将用户输入的字符串解析为浮点数列表，支持逗号或空白分隔；空或 None 返回 `default`。
- **输入**: 字符串 `s`，`default` 值（通常为列表）。
- **异常**: 无法解析时抛 `ValueError`（提示使用逗号或空格分隔）。

**`_parse_matrix_input(s, default_rows, expect_rows=None, expect_cols=None)`**:
- **作用**: 解析矩阵形式的 z 输入，支持用分号分隔行；每行内部可用逗号或空格分隔数字。
- **行为**: 若检测到分号则返回解析后的行列表（list of lists）；否则返回 `None`（调用方可按扁平列表方式进一步处理）。
- **参数校验**: 可选地检查期望行数/列数，若不匹配则抛 `ValueError`。

**`if __name__ == "__main__"`（交互式入口）**:
- 提供默认 `x_array`、`y_array`、`z_array`、`x_input` 与 `y_input`，并按交互提示顺序接收用户输入：
  1. 请求 `x_array`（逗号或空格分隔）；
  2. 请求 `y_array`（逗号或空格分隔，内部以 m/s 处理）；
  3. 请求 `z_array`（可填扁平列表或分号分隔的矩阵行）；
  4. 请求 `x_input`（单个数字）；
  5. 请求 `y_input` 单位选择：`1` = km/h（默认），`2` = m/s；随后请求 `y_input` 数值并在必要时将 km/h 转换为 m/s（除以 3.6）。
- 最终调用 `linear_interpolate_2d(x_array, y_array, z_array, x_input, y_input)` 并打印结果。脚本会在内部对输入进行排序、去重与一致性检查，必要时降级为沿 y 的 1D 插值。

**实现要点与注意事项**:
- 函数对重复坐标采取严格一致性检查：只有在重复坐标对应的 z 值完全一致时才允许合并，否则视为输入错误并抛异常以避免不明确的插值语义。
- `linear_interpolate_2d` 的内部坐标排序保证了输入不要求预先有序。
- 在边界处插值函数支持线性外推。
- 日志使用 `logging` 记录降级或去重信息，默认在脚本直接运行时设置为 `INFO`。

**交互式输入格式说明**
- **`x_array` / `y_array`**: 在交互式提示中接受以逗号或空格分隔的数字序列，例如 `1, 2, 3` 或 `1 2 3`。解析后内部使用浮点数列表。
- **`z_array`**: 支持两种输入格式：
  - 扁平列表：与 `x_array` 和 `y_array` 的长度匹配（`len(z_array) == len(x_array) * len(y_array)`），例如 `1,2,3,4`；
  - 矩阵形式：使用分号分隔行，每行内部用逗号或空格分隔，例如 `1,2,3; 4,5,6` 表示两行三列。矩阵行数应等于 `len(x_array)`，列数应等于 `len(y_array)`。
- **`x_input` / `y_input`**: 直接输入单个数字；按回车使用默认值。对于 `y_input`，在输入数值前脚本会提示选择单位：`1`（默认）表示 `km/h`，`2` 表示 `m/s`；当选择或默认为 `km/h` 时，输入值会在内部转换为 `m/s`（除以 3.6）再参与计算。注意：`y_array` 始终被视为以 `m/s` 为单位。
