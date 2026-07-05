# 打包说明

目标：打出一个 Windows 可直接双击运行的版本。推荐使用 PyInstaller 的文件夹模式，最终分发 `dist\ScreenRecorder` 整个文件夹。

## 打包命令

```powershell
conda activate screen-recorder
.\build.ps1 -Clean
```

完成后运行：

```powershell
.\dist\ScreenRecorder\ScreenRecorder.exe
```

分发给别人时，把这个文件夹整体压缩：

```text
dist\ScreenRecorder
```

对方解压后双击 `ScreenRecorder.exe` 即可运行，不需要安装 Python 或 Conda。

## ffmpeg

脚本会检查：

```text
screen_recorder\resources\ffmpeg.exe
```

如果这里还是占位文件，会尝试从当前电脑 PATH 里的 `ffmpeg` 复制真实的 `ffmpeg.exe` 进来，再打包。

如果脚本提示找不到 ffmpeg，请先把真实的 Windows 版 `ffmpeg.exe` 放到上面的路径。

## 包体积

当前如果使用 shared build 的 ffmpeg，`ffmpeg.exe` 很小，但会依赖一堆 `avcodec/avformat/avfilter` 等 DLL，最终包会很大。

更推荐使用 Windows static/essentials 版 ffmpeg：

1. 删除 `screen_recorder\resources` 里的 `*.dll`
2. 把 static 版 `ffmpeg.exe` 放到 `screen_recorder\resources\ffmpeg.exe`
3. 重新运行：

```powershell
.\build.ps1 -Clean
```

`ffmpeg-python` 这类包只是 Python 调用 ffmpeg 的包装器，不包含编码器本体，不能替代 `ffmpeg.exe`。`imageio-ffmpeg` 这类包会自带 ffmpeg 二进制，但本质上仍然是在包里携带一个 ffmpeg，可作为后续瘦身方案评估。

## ffmpeg 黑色命令行窗口

程序启动 ffmpeg 时使用了 Windows 的无窗口启动参数，正常录制时不应再弹出黑色命令行窗口。

## 单文件模式

不建议一开始就用 `--onefile`。录屏工具依赖 PyQt、音频 DLL、ffmpeg，文件夹模式更稳定、启动更快，也更容易排查问题。
