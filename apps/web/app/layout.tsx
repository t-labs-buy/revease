import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { BottomNav } from "@/components/BottomNav";
import { Footer } from "@/components/Footer";
import { AuthGate } from "@/components/AuthGate";
import { Sidebar } from "@/components/Sidebar";
import { TopBar, TopBarProvider } from "@/components/TopBar";
import { AuthProvider } from "@/contexts/AuthContext";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });

export const metadata: Metadata = {
  title: "RevEase — record once, refract into everything",
  description: "Capture a workflow, let AI generate a polished video, edit, regenerate.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning className={inter.variable}>
      <head>
        {/* set theme before paint to avoid a flash */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem('theme');var d=t?t==='dark':false;document.documentElement.classList.toggle('dark',d);}catch(e){}})();`,
          }}
        />
      </head>
      <body className="min-h-screen bg-[var(--bg)]">
        {/* AuthProvider wraps everything so the nav can show the account too;
            AuthGate keeps signed-out visitors out of every non-public route. */}
        <AuthProvider>
          {/* TopBarProvider wraps both the bar and the page so a page can portal
              its own controls into the shared header. */}
          <TopBarProvider>
            {/* Workspace shell: fixed navy sidebar, then header + page + footer. */}
            <div className="flex min-h-screen">
              <Sidebar />
              <div className="flex min-w-0 flex-1 flex-col">
                <TopBar />
                <div className="flex-1">
                  <AuthGate>{children}</AuthGate>
                </div>
                <Footer />
              </div>
            </div>
          </TopBarProvider>
          <BottomNav />
        </AuthProvider>
      </body>
    </html>
  );
}
