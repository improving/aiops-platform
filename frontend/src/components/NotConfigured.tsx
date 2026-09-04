import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

interface NotConfiguredProps {
  /** Human readable name of the tool, for example "Grafana". */
  name: string;
  /** Environment variable that must point at the tool. */
  envVar: string;
}

/** Placeholder shown where an iframe would embed an external tool. */
export default function NotConfigured({ name, envVar }: NotConfiguredProps) {
  return (
    <Card className="max-w-md">
      <CardHeader>
        <CardTitle>{name} is not configured</CardTitle>
        <CardDescription>
          Set <code className="font-mono">{envVar}</code> to the {name} URL and
          restart the frontend.
        </CardDescription>
      </CardHeader>
      <CardContent className="text-sm text-muted-foreground">
        Example:{" "}
        <code className="font-mono">{envVar}=http://localhost:3001</code>
      </CardContent>
    </Card>
  );
}
