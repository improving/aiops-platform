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
  /**
   * The page fills the window and does not scroll: the header, a small
   * title, the content with all the height that is left, and a small
   * footer. For a page whose content scrolls in itself (the chat's
   * conversation). The content's root must be `flex min-h-0 flex-1`.
   * No height is computed from a guess of what the shell takes.
   */
  fill?: boolean;
}

export default function Dashboard({
  title,
  children,
  iconUrl,
  breadcrumbs,
  fill = false,
}: DashboardProps) {
  return (
    <div
      className={
        fill
          ? // dvh: a phone's browser bar is not part of the window. The
            // minimum keeps the page usable in a very short window,
            // where it then scrolls as a whole.
            "flex h-dvh min-h-[32rem] flex-col"
          : "flex flex-col min-h-screen"
      }
    >
      <Header />
      <main
        className={
          fill
            ? "container mx-auto flex min-h-0 grow flex-col px-4 pt-4 pb-3"
            : "grow container mx-auto px-4 py-8"
        }
      >
        {breadcrumbs && <Breadcrumbs items={breadcrumbs} />}
        <h1
          className={
            fill
              ? "mb-3 flex items-center text-xl font-bold"
              : "text-3xl font-bold mb-8 flex items-center"
          }
        >
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
        <Suspense fallback={<DetailSkeleton rows={4} />}>{children}</Suspense>
      </main>
      <Footer compact={fill} />
    </div>
  );
}
