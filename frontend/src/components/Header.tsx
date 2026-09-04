import Link from "next/link";
import { usePathname } from "next/navigation";
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
import { cn } from "@/lib/utils";
import {
  CodeIcon,
  CubeIcon,
  LayersIcon,
  MagicWandIcon,
  Pencil2Icon,
} from "@radix-ui/react-icons";

const menuItems = [
  {
    label: <p className="font-bold text-2xl tracking-tight">AI Hub</p>,
    icon: <MagicWandIcon className="mr-2 h-4 w-4" />,
    href: "/",
  },
  {
    label: "Notebooks",
    icon: <Pencil2Icon className="mr-2 h-4 w-4" />,
    href: "/notebooks",
  },
  {
    label: "Models",
    icon: <CubeIcon className="mr-2 h-4 w-4" />,
    items: [
      {
        label: "Catalog",
        href: "/models/catalog",
        description: "Browse and select from a variety of AI models",
      },
      {
        label: "Instances",
        href: "/models/endpoints",
        description: "Manage and monitor your deployed model instances",
      },
    ],
  },
  {
    label: "Vector Databases",
    icon: <LayersIcon className="mr-2 h-4 w-4" />,
    items: [
      {
        label: "Catalog",
        href: "/vector-databases/catalog",
        description: "Explore available vector database solutions",
      },
      {
        label: "Instances",
        href: "/vector-databases/endpoints",
        description: "Manage your vector database deployments",
      },
    ],
  },
  {
    label: "Develop",
    icon: <CodeIcon className="mr-2 h-4 w-4" />,
    href: "/develop",
  },
];

export default function Header() {
  const { setTheme } = useTheme();
  const pathname = usePathname();

  const isActive = (href: string) => pathname.startsWith(href);

  return (
    <header className="bg-background border-b">
      <div className="container mx-auto px-4 flex justify-between items-center py-2">
        <NavigationMenu>
          <NavigationMenuList>
            {menuItems.map((item) => (
              <NavigationMenuItem key={item.label as string}>
                {item.items ? (
                  <NavigationMenuTrigger
                    className={cn(
                      item.items.some((subItem) => isActive(subItem.href)) &&
                        "font-bold text-primary"
                    )}
                  >
                    {item.icon}
                    {item.label}
                  </NavigationMenuTrigger>
                ) : (
                  <Link href={item.href} legacyBehavior passHref>
                    <NavigationMenuLink
                      className={cn(
                        navigationMenuTriggerStyle(),
                        isActive(item.href) && "font-bold text-primary"
                      )}
                    >
                      {item.icon}
                      {item.label}
                    </NavigationMenuLink>
                  </Link>
                )}
                {item.items && (
                  <NavigationMenuContent>
                    <ul className="grid w-[400px] gap-3 p-4 md:w-[500px] md:grid-cols-2 lg:w-[600px]">
                      {item.items.map((subItem) => (
                        <li key={subItem.href}>
                          <NavigationMenuLink asChild>
                            <Link
                              href={subItem.href}
                              className={cn(
                                "block select-none space-y-1 rounded-md p-3 leading-none no-underline outline-hidden transition-colors hover:bg-accent hover:text-accent-foreground focus:bg-accent focus:text-accent-foreground",
                                isActive(subItem.href) &&
                                  "bg-accent text-accent-foreground"
                              )}
                            >
                              <div className="text-sm font-medium leading-none">
                                {subItem.label}
                              </div>
                              <p className="line-clamp-2 text-sm leading-snug text-muted-foreground">
                                {subItem.description}
                              </p>
                            </Link>
                          </NavigationMenuLink>
                        </li>
                      ))}
                    </ul>
                  </NavigationMenuContent>
                )}
              </NavigationMenuItem>
            ))}
          </NavigationMenuList>
        </NavigationMenu>
        <div className="flex items-center space-x-4">
          <div className="flex items-center ml-4">
            <ThemeDropdown setTheme={setTheme} />
          </div>
          <Avatar>
            <AvatarImage
              src="https://github.com/infracloudio.png"
              alt="User avatar"
            />
            <AvatarFallback>IC</AvatarFallback>
          </Avatar>
        </div>
      </div>
    </header>
  );
}
