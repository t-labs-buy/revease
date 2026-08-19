"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";
import {
  AuthLink,
  AuthShell,
  Field,
  FormError,
  SubmitButton,
} from "@/components/AuthForm";

/** `useSearchParams` (for the post-login `?next=` redirect) opts a component out
 *  of prerendering, so it lives behind a Suspense boundary here. */
export default function LoginPage() {
  return (
    <Suspense fallback={<LoginFallback />}>
      <LoginForm />
    </Suspense>
  );
}

function LoginFallback() {
  return (
    <AuthShell
      title="Welcome back"
      subtitle="Sign in to your workspace"
      footer={
        <>
          Don&apos;t have an account? <AuthLink href="/register">Create one</AuthLink>
        </>
      }
    >
      <div className="h-[232px]" />
    </AuthShell>
  );
}

function LoginForm() {
  const { login } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const justRegistered = searchParams.get("registered") === "1";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Arriving straight from /register: prefill the email that was just used, so
  // only the password has to be typed again. Read once, then clear.
  useEffect(() => {
    if (!justRegistered) return;
    try {
      const stored = sessionStorage.getItem("revease.registered_email");
      if (stored) {
        setEmail(stored);
        sessionStorage.removeItem("revease.registered_email");
      }
    } catch {
      /* no prefill available */
    }
  }, [justRegistered]);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    // Our own checks rather than the browser's tooltips, so every failure lands
    // in the same banner below.
    if (!email.trim() || !password) {
      setError("Enter your email and password");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      // Return them to whatever they were trying to reach before the redirect.
      router.replace(searchParams.get("next") || "/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign in");
      setBusy(false); // stay on the form; on success we're navigating away
    }
  };

  return (
    <AuthShell
      title="Welcome back"
      subtitle="Sign in to your workspace"
      footer={
        <>
          Don&apos;t have an account? <AuthLink href="/register">Create one</AuthLink>
        </>
      }
    >
      <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
        {justRegistered && !error && (
          <p
            role="status"
            className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-500"
          >
            Account created — sign in to continue.
          </p>
        )}
        <FormError message={error} />
        <Field
          label="Email"
          type="email"
          autoComplete="email"
          autoFocus
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@company.com"
        />
        <Field
          label="Password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="••••••••"
        />
        <SubmitButton busy={busy}>Sign in</SubmitButton>
      </form>
    </AuthShell>
  );
}
