import { Component, StrictMode, type ErrorInfo, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

class AppErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("MineM render failed", error, info);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <main className="fatal-error" role="alert">
        <section>
          <strong>MineM 页面遇到异常</strong>
          <p>你的素材数据没有丢失。请重新加载页面；如果问题持续，请重启 MineM。</p>
          <button type="button" onClick={() => window.location.reload()}>重新加载</button>
          <details>
            <summary>查看错误信息</summary>
            <code>{this.state.error.message || "未知错误"}</code>
          </details>
        </section>
      </main>
    );
  }
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppErrorBoundary>
      <App />
    </AppErrorBoundary>
  </StrictMode>
);
