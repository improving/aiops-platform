import React from "react";
import Image from "next/image";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { RefreshButton } from "@/components/RefreshButton";

interface DisplayCardProps {
  icon?: string | React.ReactNode;
  title: React.ReactNode;
  description?: React.ReactNode;
  content?: React.ReactNode;
  footer?: React.ReactNode;
  /**
   * Where the content sits when cards of one row differ in height. The
   * default lets the header take the spare height, so the content ends at
   * the bottom; "top" starts the content right under the header on every
   * card (lists whose cards gain or lose a banner, a progress line or a
   * footer action), and the footer still sits at the bottom.
   */
  align?: "bottom" | "top";
  className?: string;
  onClick?: () => void;
  onRefresh?: () => Promise<void>;
}

export function DisplayCard({
  icon,
  title,
  description,
  content,
  footer,
  align = "bottom",
  className,
  onClick,
  onRefresh,
}: DisplayCardProps) {
  return (
    <Card className={`flex flex-col h-full ${className}`} onClick={onClick}>
      <CardHeader className={align === "top" ? undefined : "grow"}>
        <div className="flex justify-between">
          <div className="flex items-start space-x-4">
            {icon &&
              (typeof icon === "string" ? (
                <div className="relative w-9 h-9">
                  <Image
                    src={icon}
                    alt="Icon"
                    fill
                    sizes="36px"
                    className="rounded-md object-contain"
                  />
                </div>
              ) : (
                icon
              ))}
            <div>
              <CardTitle>{title}</CardTitle>
              {description && <CardDescription>{description}</CardDescription>}
            </div>
          </div>
          {onRefresh && <RefreshButton onRefresh={onRefresh} />}
        </div>
      </CardHeader>
      {content && (
        <CardContent className={align === "top" ? "grow" : undefined}>
          {content}
        </CardContent>
      )}
      {footer && <CardFooter className="mt-auto">{footer}</CardFooter>}
    </Card>
  );
}
