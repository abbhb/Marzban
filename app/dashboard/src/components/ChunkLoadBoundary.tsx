import { CHUNK_RELOAD_KEY, failBoot } from "boot";
import { Component, ErrorInfo, ReactNode } from "react";

type Props = { children: ReactNode };
type State = { error: Error | null; reloading: boolean };

const isChunkLoadError = (error: Error) =>
  /dynamically imported module|importing a module script failed|unable to preload css|loading chunk|chunkloaderror/i.test(
    error.message
  );

export class ChunkLoadBoundary extends Component<Props, State> {
  state: State = { error: null, reloading: false };

  static getDerivedStateFromError(error: Error): State {
    return { error, reloading: false };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Dashboard page failed to load", error, info);
    if (!isChunkLoadError(error)) {
      failBoot();
      return;
    }

    let alreadyRetried = true;
    try {
      alreadyRetried = sessionStorage.getItem(CHUNK_RELOAD_KEY) === location.href;
      if (!alreadyRetried) {
        sessionStorage.setItem(CHUNK_RELOAD_KEY, location.href);
      }
    } catch (storageError) {
      // Without session storage, avoid an automatic reload loop.
    }

    if (!alreadyRetried) {
      this.setState({ reloading: true });
      location.reload();
      return;
    }
    failBoot();
  }

  render() {
    const { error, reloading } = this.state;
    if (!error) return this.props.children;
    if (reloading) return null;

    const isChinese = document.documentElement.lang.toLowerCase().startsWith("zh");
    return (
      <main
        role="alert"
        style={{
          minHeight: "100dvh",
          display: "grid",
          placeItems: "center",
          padding: 24,
          background: "var(--chakra-colors-app-canvas, #eaf1fa)",
        }}
      >
        <section style={{ maxWidth: 420, textAlign: "center" }}>
          <h1>{isChinese ? "页面资源加载失败" : "Page resources failed to load"}</h1>
          <p>
            {isChinese
              ? "可能刚完成版本更新，请刷新后重试。"
              : "The dashboard may have just been updated. Reload to try again."}
          </p>
          <button type="button" onClick={() => location.reload()}>
            {isChinese ? "刷新重试" : "Reload"}
          </button>
        </section>
      </main>
    );
  }
}
