"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import Dashboard from "@/components/Dashboard";

export function DisplayCard({
  title,
  description,
  buttons,
}: {
  title: string;
  description: string;
  buttons: { link: string; text: string; variant: "default" | "secondary" }[];
}) {
  return (
    <Card className="shadow-lg rounded-lg">
      <CardHeader>
        <CardTitle className="text-lg font-semibold">{title}</CardTitle>
        <CardDescription className="text-sm">{description}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col items-center">
        <div className="flex flex-row gap-2 mb-3 w-full">
          {buttons.map((button, index) => (
            <Link key={index} href={button.link} passHref>
              <Button variant={button.variant} className="w-full py-2">
                {button.text}
              </Button>
            </Link>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

export default function Home() {
  return (
    <Dashboard title="Welcome to Hub">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <DisplayCard
          title="Models"
          description="Explore our AI models"
          buttons={[
            {
              link: "/models/catalog",
              text: "View Catalog",
              variant: "default",
            },
            {
              link: "/models/endpoints",
              text: "View Endpoints",
              variant: "secondary",
            },
          ]}
        />
        <DisplayCard
          title="Vector Databases"
          description="Explore our vector databases"
          buttons={[
            {
              link: "/vector-databases/catalog",
              text: "View Catalog",
              variant: "default",
            },
            {
              link: "/vector-databases/endpoints",
              text: "View Endpoints",
              variant: "secondary",
            },
          ]}
        />
      </div>
    </Dashboard>
  );
}
