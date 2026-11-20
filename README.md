# audio-sampler-loop

采样器加载钢琴音色后，音高整体错位、循环点还咔哒响：音高比把半音差 `(note-root)/12` 直接当成频率乘数，八度关系整体错位；循环点不做交叉淡化，回绕接缝处波形跳变、产生爆音；循环区间允许 `loop_start >= loop_end`，播放器会卡进死循环；力度曲线固定为线性，弱奏没有动态；缺音区时不做回退，直接返回空采样；渲染长度按浮点秒截断，长音会累计漂移；释放尾巴从循环点直接截断，收尾有咔哒声；循环区间越界不做校验，运行中索引错误；批量渲染共用循环状态，音符之间互相串；音区重叠不报错，运行时随机取一个。sampler/voice.py 是核心，tests/test_voice.py 15个红。要修的是：…

## 运行方式

在仓库根目录执行：

```powershell
python -m pytest tests -q
```

初始基线必须恰好是：

```text
15 failed
```

不应出现 collection、import 或 syntax error。所有采样均为单声道 `list[float]`，音区为 `{"root_note", "low", "high"}`；仅使用标准库 `math` 与 pytest，离线、无随机、不 sleep。

## 字段表

| 字段 | 取值 |
| --- | --- |
| 所属领域 | 游戏、图形与多媒体 |
| 子方向 | 音视频处理 |
| 任务类型 | Bugfix |
| 语言/框架 | Python 3, pytest |
| 环境可复现等级 | 无外部依赖 |

## 约束

`tests/` 不可修改。只修复 `sampler/voice.py` 中八个函数的实现，保持现有公开签名、异常类型与测试契约不变。
