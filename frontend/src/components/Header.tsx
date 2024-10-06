import Link from "next/link";
import {
  NavigationMenu,
  NavigationMenuContent,
  NavigationMenuItem,
  NavigationMenuLink,
  NavigationMenuList,
  NavigationMenuTrigger,
  navigationMenuTriggerStyle,
} from "@/components/ui/navigation-menu";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { useTheme } from "next-themes";
import { ThemeDropdown } from "./ThemeDropdown";
import { HomeIcon } from "@radix-ui/react-icons";

const menuItems = [
  {
    label: "Models",
    items: [
      { 
        label: "Catalog", 
        href: "/models/catalog/",
        description: "Browse and select from a variety of AI models"
      },
      { 
        label: "Instances", 
        href: "/models/endpoints",
        description: "Manage and monitor your deployed model instances"
      },
    ],
  },
  {
    label: "Vector Databases",
    items: [
      { 
        label: "Catalog", 
        href: "/vector-databases/catalog",
        description: "Explore available vector database solutions"
      },
      { 
        label: "Instances", 
        href: "/vector-databases/endpoints",
        description: "Manage your vector database deployments"
      },
    ],
  },
];

export default function Header() {
  const { setTheme } = useTheme();

  return (
    <header className="bg-background border-b">
      <div className="container mx-auto px-4 flex justify-between items-center py-2">
        <NavigationMenu>
          <NavigationMenuList>
            <NavigationMenuItem>
              <Link href="/" legacyBehavior passHref>
                <NavigationMenuLink className={navigationMenuTriggerStyle()}>
                  <p className="font-bold text-2xl text-primary tracking-tight">
                    AI Hub
                  </p>
                </NavigationMenuLink>
              </Link>
            </NavigationMenuItem>
            <NavigationMenuItem>
              <Link href="/notebooks" legacyBehavior passHref>
                <NavigationMenuLink className={navigationMenuTriggerStyle()}>
                  Notebooks
                </NavigationMenuLink>
              </Link>
            </NavigationMenuItem>
            {menuItems.map((item) => (
              <NavigationMenuItem key={item.label}>
                <NavigationMenuTrigger>{item.label}</NavigationMenuTrigger>
                <NavigationMenuContent>
                  <ul className="grid w-[400px] gap-3 p-4 md:w-[500px] md:grid-cols-2 lg:w-[600px]">
                    {item.items.map((subItem) => (
                      <li key={subItem.href}>
                        <NavigationMenuLink asChild>
                          <Link
                            href={subItem.href}
                            className="block select-none space-y-1 rounded-md p-3 leading-none no-underline outline-none transition-colors hover:bg-accent hover:text-accent-foreground focus:bg-accent focus:text-accent-foreground"
                          >
                            <div className="text-sm font-medium leading-none">{subItem.label}</div>
                            <p className="line-clamp-2 text-sm leading-snug text-muted-foreground">
                              {subItem.description}
                            </p>
                          </Link>
                        </NavigationMenuLink>
                      </li>
                    ))}
                  </ul>
                </NavigationMenuContent>
              </NavigationMenuItem>
            ))}
          </NavigationMenuList>
        </NavigationMenu>
        <div className="flex items-center space-x-4">
          <div className="flex items-center ml-4">
            <ThemeDropdown setTheme={setTheme} />
          </div>
          <Avatar>
            <AvatarImage src="https://github.com/infracloudio.png" alt="User avatar" />
            <AvatarFallback>CN</AvatarFallback>
          </Avatar>
        </div>
      </div>
    </header>
  );
}
