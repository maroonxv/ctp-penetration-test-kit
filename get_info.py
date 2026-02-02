import ctypes

# 加载你下载的 DLL
try:
    # 直接加载 lib 目录下的 dll
    lib_path = "./lib/WinDataCollect.dll"
    
    print(f"尝试加载 DLL: {lib_path}")
    lib = ctypes.WinDLL(lib_path)
    print("成功加载 WinDataCollect.dll")
except OSError as e:
    print(f"加载失败: {e}")
    if "WinError 193" in str(e):
        print("WinError 193 通常表示 DLL 位数与 Python 位数不匹配。")
        print(f"当前 Python 位数: {ctypes.sizeof(ctypes.c_void_p) * 8}")
    exit()
except Exception as e:
    print(f"加载失败: {e}")
    exit()

# 根据 .h 文件的定义，准备参数
# 缓冲区长度通常固定为 512 或以上，官方建议 273 以上
info_buffer = ctypes.create_string_buffer(512)
info_len = ctypes.c_int(0)

# 调用函数 (根据 .h 文件确认函数名为 CTP_GetSystemInfo)
# 如果是 V2 版本请尝试 lib.CTP_GetSystemInfoV2
try:
    func_name = "CTP_GetSystemInfo"
    if hasattr(lib, "CTP_GetSystemInfo"):
        func = lib.CTP_GetSystemInfo
    elif hasattr(lib, "CTP_GetSystemInfoV2"):
        func = lib.CTP_GetSystemInfoV2
        func_name = "CTP_GetSystemInfoV2"
    elif hasattr(lib, "?CTP_GetSystemInfo@@YAHPEADAEAH@Z"): # C++ Mangled name for 64-bit
        func = lib["?CTP_GetSystemInfo@@YAHPEADAEAH@Z"]
        func_name = "?CTP_GetSystemInfo@@YAHPEADAEAH@Z"
    else:
        # 尝试列出可能的函数名或者抛出更明确的错误
        raise Exception("找不到 CTP_GetSystemInfo 或 CTP_GetSystemInfoV2 函数")

    print(f"调用函数: {func_name}")
    res = func(info_buffer, ctypes.byref(info_len))
    
    if info_len.value > 0:
        # 获取原始字节数据
        raw_data = info_buffer.raw[:info_len.value]
        
        # 尝试解码用于显示 (仅供参考)
        try:
            display_info = raw_data.decode('gbk', errors='ignore')
        except:
            display_info = str(raw_data)

        print("-" * 30)
        print("采集到的穿透式信息为 (这就是你要的证据数据):")
        print(display_info)
        print("-" * 30)
        
        # 将结果保存为 .dat 文件 (使用二进制写入以确保数据完全一致)
        with open("terminal_info.dat", "wb") as f:
            f.write(raw_data)
        print("已自动保存为 terminal_info.dat")
    else:
        print("采集失败，长度为 0。请检查是否拥有管理员权限。")
except Exception as e:
    print(f"调用出错: {e}")
