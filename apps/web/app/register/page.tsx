"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";
import {
  AuthLink,
  AuthShell,
  Field,
  FormError,
  SubmitButton,
} from "@/components/AuthForm";

const MIN_PASSWORD = 8; // mirrors the API's rule, so we can say so before submitting

// Good enough to catch a typo before a round-trip; the API is the real authority.
const looksLikeEmail = (value: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim());

export default function RegisterPage() {
  const { register } = useAuth();
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    // Validated here rather than by the browser's built-in tooltips, so every
    // failure shows up in the same banner and nothing can fail silently.
    if (!looksLikeEmail(email)) {
      setError("Enter a valid email address, like you@company.com");
      return;
    }
    if (password.length < MIN_PASSWORD) {
      setError(`Use at least ${MIN_PASSWORD} characters for your password`);
      return;
    }
    if (password !== confirm) {
      setError("Those passwords don't match");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await register(email, password, name);
      // Creating an account doesn't sign you in — hand off to the login screen.
      // The email rides in sessionStorage rather than the URL so it stays out of
      // browser history and referrers.
      try {
        sessionStorage.setItem("revease.registered_email", email);
      } catch {
        /* prefill is a nicety; the banner still shows without it */
      }
      router.replace("/login?registered=1");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create your account");
      setBusy(false);
    }
  };

  return (
    <AuthShell
      title="Create your workspace"
      subtitle="Your recordings, docs and skills stay private to you"
      footer={
        <>
          Already have an account? <AuthLink href="/login">Sign in</AuthLink>
        </>
      }
    >
      <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
        <FormError message={error} />
        <Field
          label="Name"
          autoComplete="name"
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Your name"
        />
        <Field
          label="Email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@company.com"
        />
        <Field
          label="Password"
          type="password"
          autoComplete="new-password"
          hint={`At least ${MIN_PASSWORD} characters`}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="••••••••"
        />
        <Field
          label="Confirm password"
          type="password"
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          placeholder="••••••••"
        />
        <SubmitButton busy={busy}>Create account</SubmitButton>
      </form>
    </AuthShell>
  );
}
