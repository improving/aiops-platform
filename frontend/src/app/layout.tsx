import "./globals.css";
import { Inter } from "next/font/google";
import { ThemeProvider } from "@/components/ui/theme-provider";

const inter = Inter({ subsets: ["latin"] });

export const metadata = {
  title: "Model Hub",
  description: "Explore and deploy AI models",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
