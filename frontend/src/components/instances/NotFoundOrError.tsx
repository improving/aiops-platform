import { AxiosError } from "axios";
import { parseApiError } from "@/lib/utils";

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/**
 * The fallback the three instance detail pages render when the initial
 * fetch did not produce an instance: a 404 reads "<Noun> not found", any
 * other error reads "Could not load this <noun>: <description>". `noun`
 * is the lowercase phrase ("model instance", "notebook", "vector database
 * instance").
 */
export function NotFoundOrError({
  error,
  noun,
}: {
  error: unknown;
  noun: string;
}) {
  if (error instanceof AxiosError && error.response?.status === 404) {
    return <div>{`${capitalize(noun)} not found`}</div>;
  }
  if (error) {
    return (
      <div>
        Could not load this {noun}: {parseApiError(error).description}
      </div>
    );
  }
  return <div>{`${capitalize(noun)} not found`}</div>;
}
