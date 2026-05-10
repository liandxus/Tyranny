import tkinter as tk

def main():
    # 创建主窗口
    window = tk.Tk()
    window.title("IndeXar")
    window.geometry("900x600")

    # 暂时放一个占位标签，确认窗口能正常显示
    label = tk.Label(window, text="IndeXar 启动成功。", font=("Arial", 16))
    label.pack(pady=30)

    # 进入主循环，等待用户操作
    window.mainloop()

if __name__ == "__main__":
    main()