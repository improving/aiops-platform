import { ReloadIcon } from "@radix-ui/react-icons";
import { Button } from "@/components/ui/button";
import { useState } from "react";

interface RefreshButtonProps {
  onRefresh: () => Promise<void>;
}

export function RefreshButton({ onRefresh }: RefreshButtonProps) {
  const [isRefreshing, setIsRefreshing] = useState(false);

  const handleRefresh = async () => {
    setIsRefreshing(true);
    await onRefresh();
    setIsRefreshing(false);
  };

  return (
    <Button
      onClick={handleRefresh}
      icon={<ReloadIcon className="h-4 w-4" />}
      loading={isRefreshing}
      loadingIcon={<ReloadIcon className="h-4 w-4" />}
      variant="outline"
    ></Button>
  );
}
