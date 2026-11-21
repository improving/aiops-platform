export default function Footer({ compact = false }: { compact?: boolean }) {
  return (
    <footer
      className={
        compact
          ? "bg-background border-t py-2 text-sm"
          : "bg-background border-t py-4 mt-8"
      }
    >
      <div className="container mx-auto text-center text-muted-foreground">
        <p>
          &copy;{" "}
          <span suppressHydrationWarning>{new Date().getFullYear()}</span>{" "}
          Improving. Licensed under Apache-2.0.
        </p>
      </div>
    </footer>
  );
}
