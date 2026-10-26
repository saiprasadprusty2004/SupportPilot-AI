import { Component, lazy, Suspense, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Box, LockKeyhole, Sparkles } from "lucide-react";
import { useTheme } from "./ThemeProvider";
import { ProviderIcon } from "./ui";
import type { Connection } from "../lib/types";

const Scene = lazy(() => import("./AgentScene"));
class SceneBoundary extends Component<
  { children: ReactNode; fallback: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}
function StaticCore() {
  return (
    <div className="static-core" aria-hidden="true">
      <div className="orbit orbit-one" />
      <div className="orbit orbit-two" />
      <div className="static-crystal">
        <Box size={72} strokeWidth={0.9} />
      </div>
      <div className="orbit orbit-three" />
    </div>
  );
}
export default function Constellation({
  graphics = true,
  connections = [],
  active = false,
}: {
  graphics?: boolean;
  connections?: Connection[];
  active?: boolean;
}) {
  const { resolved } = useTheme();
  const ref = useRef<HTMLDivElement>(null);
  const [intersecting, setIntersecting] = useState(false);
  const [fallback, setFallback] = useState(false);
  const [compatible, setCompatible] = useState(false);
  useEffect(() => {
    const motion = matchMedia("(prefers-reduced-motion: reduce)");
    const mobile = matchMedia("(max-width: 600px)");
    const check = () => {
      if (!graphics || motion.matches || mobile.matches) {
        setCompatible(false);
        return;
      }
      const canvas = document.createElement("canvas");
      const gl = canvas.getContext("webgl2") || canvas.getContext("webgl");
      setCompatible(!motion.matches && !mobile.matches && !!gl);
      gl?.getExtension("WEBGL_lose_context")?.loseContext();
    };
    check();
    motion.addEventListener("change", check);
    mobile.addEventListener("change", check);
    const observer = new IntersectionObserver(([entry]) =>
      setIntersecting(entry.isIntersecting),
    );
    if (ref.current) observer.observe(ref.current);
    return () => {
      observer.disconnect();
      motion.removeEventListener("change", check);
      mobile.removeEventListener("change", check);
    };
  }, [graphics]);
  const enabled = graphics && compatible && intersecting && !fallback;
  const connected = (provider: string) =>
    connections.some((c) => c.provider === provider && c.status === "active");
  return (
    <div
      ref={ref}
      className="constellation"
      role="img"
      aria-label="3D agent core connecting Gmail, Slack, and Google Drive. All actions require your approval."
    >
      <div className="scene-glow" />
      <div className="scene-canvas">
        {enabled ? (
          <SceneBoundary fallback={<StaticCore />}>
            <Suspense fallback={<StaticCore />}>
              <Scene
                dark={resolved === "dark"}
                onFallback={() => setFallback(true)}
              />
            </Suspense>
          </SceneBoundary>
        ) : (
          <StaticCore />
        )}
      </div>
      <div
        className={`scene-node node-gmail ${connected("gmail") ? "" : "scene-disconnected"}`}
      >
        <span className="scene-provider">
          <ProviderIcon provider="gmail" size={23} />
        </span>
        <span>
          Gmail
          <small>{connected("gmail") ? "Connected" : "Ready to connect"}</small>
        </span>
        <i />
      </div>
      <div
        className={`scene-node node-slack ${connected("slack") ? "" : "scene-disconnected"}`}
      >
        <span className="scene-provider">
          <ProviderIcon provider="slack" size={23} />
        </span>
        <span>
          Slack
          <small>{connected("slack") ? "Connected" : "Ready to connect"}</small>
        </span>
        <i />
      </div>
      <div
        className={`scene-node node-drive ${connected("googledrive") ? "" : "scene-disconnected"}`}
      >
        <span className="scene-provider">
          <ProviderIcon provider="googledrive" size={23} />
        </span>
        <span>
          Drive
          <small>
            {connected("googledrive") ? "Connected" : "Ready to connect"}
          </small>
        </span>
        <i />
      </div>
      <div className="scene-agent-label">
        <Sparkles size={12} /> {active ? "AGENT AT WORK" : "SUPPORTPILOT AGENT"}
      </div>
      <div className="scene-security">
        <LockKeyhole size={11} /> Connected. Grounded. In your control.
      </div>
    </div>
  );
}
