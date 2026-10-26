import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, LoaderCircle, ShieldCheck, Sparkles } from "lucide-react";
import Constellation from "../components/Constellation";
import { Button, Logo } from "../components/ui";
import { api, post } from "../lib/api";

export default function Login() {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const client = useQueryClient();
  const options = useQuery({
    queryKey: ["auth-options"],
    queryFn: () =>
      api<{ google_enabled: boolean; demo_enabled: boolean }>("/auth/options"),
    retry: false,
  });
  const location = useLocation();
  const navigate = useNavigate();
  const params = new URLSearchParams(location.search);
  const invite = location.pathname === "/invite" ? params.get("token") : null;
  const reset = location.pathname === "/reset" ? params.get("token") : null;
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await post(
        invite
          ? "/auth/accept-invite"
          : reset
            ? "/auth/reset-password"
            : "/auth/login",
        invite
          ? { token: invite, name, password }
          : reset
            ? { token: reset, password }
            : { email, password },
      );
      if (reset) {
        window.location.assign("/");
        return;
      }
      await client.invalidateQueries({ queryKey: ["session"] });
      navigate("/", { replace: true });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function demo() {
    setBusy(true);
    try {
      await post("/auth/demo", {});
      await client.invalidateQueries({ queryKey: ["session"] });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="login-page">
      <div className="login-visual">
        <Logo />
        <div className="login-hero">
          <span className="eyebrow">
            <Sparkles size={13} /> A LITTLE LESS BUSYWORK
          </span>
          <h1>
            Great support.
            <br />A little more
            <br />
            <span>effortless.</span>
          </h1>
          <p>
            Your tools, your knowledge, your AI teammate.
            <br />
            One thoughtful workspace.
          </p>
          <Constellation />
        </div>
        <div className="login-footer">
          <ShieldCheck size={14} /> Your accounts. Your data. Your control.
        </div>
      </div>
      <div className="login-form-side">
        <div className="login-form">
          <div className="login-small-logo">
            <Logo />
          </div>
          <span className="eyebrow">WELCOME TO SUPPORTPILOT</span>
          <h2>
            {invite
              ? "Your team is waiting."
              : reset
                ? "A fresh start."
                : "Good to have you back."}
          </h2>
          <p>
            {invite
              ? "Accept your invitation and make yourself at home."
              : reset
                ? "Choose a strong new password for your account."
                : "Sign in and give your support a little lift."}
          </p>
          <form onSubmit={submit}>
            {invite && (
              <label>
                Your name
                <input
                  required
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  maxLength={100}
                />
              </label>
            )}
            {!invite && !reset && (
              <label>
                Email address
                <input
                  type="email"
                  placeholder="you@yourcompany.com"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
              </label>
            )}
            <label>
              Password
              <input
                type="password"
                placeholder={
                  invite || reset
                    ? "At least 12 characters"
                    : "Enter your password"
                }
                autoComplete={
                  invite || reset ? "new-password" : "current-password"
                }
                minLength={invite || reset ? 12 : 1}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </label>
            {error && (
              <div className="field-error" role="alert">
                {error}
              </div>
            )}
            <Button disabled={busy} type="submit">
              {busy ? <LoaderCircle size={16} className="spin" /> : null}
              {invite
                ? "Join your workspace"
                : reset
                  ? "Update password"
                  : "Sign in"}
              <ArrowRight size={16} />
            </Button>
          </form>
          {!reset && options.data?.google_enabled && (
            <>
              <div className="login-divider">
                <span>or continue with</span>
              </div>
              <a
                className="button button-secondary google-login"
                href={
                  "/api/v1/auth/google/start" +
                  (invite ? "?invite=" + encodeURIComponent(invite) : "")
                }
              >
                <span className="google-g">G</span>Google
              </a>
            </>
          )}
          {options.data?.demo_enabled && (
            <div className="login-demo">
              <span>Just taking a look?</span>
              <button className="text-button" onClick={demo} disabled={busy}>
                Open demo workspace
                <ArrowRight size={13} />
              </button>
              <Link to="/preview">Explore the design preview</Link>
            </div>
          )}
          <small className="login-invite-note">
            Invite-only workspaces. Ask your workspace owner for access.
          </small>
        </div>
      </div>
    </div>
  );
}
