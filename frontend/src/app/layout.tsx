import "./globals.css";
import { Inter } from "next/font/google";
import { Toaster } from "@/components/ui/toaster";
import { ThemeProvider } from "@/components/ui/theme-provider";
import { AuthProvider } from "@/components/AuthProvider";
import { RuntimeConfigProvider } from "@/lib/runtimeConfig";

const inter = Inter({ subsets: ["latin"] });

export const metadata = {
  title: "AI Hub",
  description: "Explore and deploy AI services",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    // next-themes sets class and color-scheme on <html> before hydration.
    <html lang="en" suppressHydrationWarning>
      <body className={inter.className}>
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <AuthProvider>
            <RuntimeConfigProvider>{children}</RuntimeConfigProvider>
          </AuthProvider>
          <Toaster />
        </ThemeProvider>
      </body>
    </html>
  );
}
