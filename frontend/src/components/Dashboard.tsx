import { Suspense } from "react";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import { DetailSkeleton } from "@/components/LoadingState";
import { Breadcrumbs, type Crumb } from "@/components/Breadcrumbs";

interface DashboardProps {
  title: string;
  children: React.ReactNode;
  iconUrl?: string; // Optional prop for the icon URL
  breadcrumbs?: Crumb[];
}

export default function Dashboard({
  title,
  children,
  iconUrl,
  breadcrumbs,
}: DashboardProps) {
  return (
    <div className="flex flex-col min-h-screen">
      <Header />
      <main className="grow container mx-auto px-4 py-8">
        {breadcrumbs && <Breadcrumbs items={breadcrumbs} />}
        <h1 className="text-3xl font-bold mb-8 flex items-center">
          <span>{title}</span>
          {iconUrl && (
            <a
              href={iconUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="ml-2"
            >
              <svg
                width="30"
                height="30"
                viewBox="0 0 24 24"
                xmlns="http://www.w3.org/2000/svg"
              >
                <path
                  fill="#00F"
                  d="M18 10.82a1 1 0 0 0-1 1V19a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1h7.18a1 1 0 0 0 0-2H5a3 3 0 0 0-3 3v11a3 3 0 0 0 3 3h11a3 3 0 0 0 3-3v-7.18a1 1 0 0 0-1-1m3.92-8.2a1 1 0 0 0-.54-.54A1 1 0 0 0 21 2h-6a1 1 0 0 0 0 2h3.59L8.29 14.29a1 1 0 0 0 0 1.42 1 1 0 0 0 1.42 0L20 5.41V9a1 1 0 0 0 2 0V3a1 1 0 0 0-.08-.38"
                />
              </svg>
            </a>
          )}
        </h1>
        <Suspense fallback={<DetailSkeleton rows={4} />}>
          {children}
        </Suspense>
      </main>
      <Footer />
    </div>
  );
}
