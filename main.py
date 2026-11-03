import html
import re
import threading
import webbrowser
from io import BytesIO
from urllib.parse import urljoin

import customtkinter as ctk
import requests
from PIL import Image, ImageDraw
from tkinter import PhotoImage

ctk.set_appearance_mode("dark")
root = ctk.CTk()
root.title("Github User Search")
root.geometry("900x560+300+120")
root.resizable(False, False)
root.configure(fg_color="#141d2f")
icon_image = PhotoImage(file='assets/logo.png')
root.iconphoto(False, icon_image)

DEFAULT_AVATAR = "https://avatars.githubusercontent.com/u/113606119?v=4"
HEADERS = {"User-Agent": "Mozilla/5.0"}

MAX_ITEMS = 50
CARD_WIDTH = 440

tabs_config = {
    "Repos": {
        "params": {"per_page": 100, "sort": "updated"},
        "title": "Repositories (latest {} updated)",
        "empty": "No public repositories",
        "show_owner": False,
    },
    "Stars": {
        "params": {"per_page": 100},
        "title": "Starred repos (latest {} starred)",
        "empty": "No starred repositories",
        "show_owner": True,
    },
}
lists = {name: {"url": None, "loaded": False, "loading": False} for name in tabs_config}
card = {"login": None, "page_url": None, "loaded": False, "loading": False}
search_id = 0  # bumped on every search so old results get ignored


def val(data, key, default="Not Available"):
    value = data.get(key)
    return str(value).strip() if value not in (None, "") else default


def shorten(text, limit):
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    return text[:limit - 1].rstrip() + "..."


def circle_image(content=None, size=(100, 100)):
    if content:
        img = Image.open(BytesIO(content)).convert("RGBA")
        img = img.resize(size, Image.Resampling.LANCZOS)
    else:
        img = Image.new("RGBA", size, "#3a4a6b")

    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size[0] - 1, size[1] - 1), fill=255)

    out = Image.new("RGBA", size, (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return ctk.CTkImage(light_image=out, dark_image=out, size=size)


def set_avatar(img):
    label_avatar.configure(image=img)
    label_avatar.image = img  # keep a reference or tk drops it


# repos / stars tabs
def clear_list(name, message):
    st = lists[name]
    st.update(url=None, loaded=False, loading=False)
    for w in st["scroll"].winfo_children():
        w.destroy()
    st["info"].configure(text=message)


def add_repo(name, repo):
    frame = ctk.CTkFrame(lists[name]["scroll"], fg_color="#141d2f", corner_radius=10)
    frame.pack(fill="x", padx=4, pady=4)

    if tabs_config[name]["show_owner"]:
        title = repo.get("full_name")
    else:
        title = repo.get("name")

    label = ctk.CTkLabel(frame, text=shorten(title or "N/A", 38),
                         font=("Courier New", 16, "bold"), text_color="#0079ff",
                         cursor="hand2", anchor="w")
    label.pack(anchor="w", padx=12, pady=(8, 0))
    url = repo.get("html_url")
    if url:
        label.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))

    desc = ctk.CTkLabel(frame, text=shorten(val(repo, "description", "No description"), 90),
                        anchor="w", justify="left", wraplength=380, text_color="#c0c8d8")
    desc.pack(anchor="w", padx=12)

    info = []
    if repo.get("language"):
        info.append(repo["language"])
    info.append(f"★ {repo.get('stargazers_count', 0)}")
    info.append(f"⑂ {repo.get('forks_count', 0)}")
    if repo.get("fork"):
        info.append("forked")
    ctk.CTkLabel(frame, text="   ".join(info), font=("Space Mono", 12),
                 text_color="#8b98b8", anchor="w").pack(anchor="w", padx=12, pady=(2, 8))


def show_list(name, items, sid):
    if sid != search_id:
        return
    st = lists[name]
    st["loaded"] = True
    st["loading"] = False
    for w in st["scroll"].winfo_children():
        w.destroy()

    if not items:
        st["info"].configure(text=tabs_config[name]["empty"])
        return

    items = items[:MAX_ITEMS]
    st["info"].configure(text=tabs_config[name]["title"].format(len(items)))
    for item in items:
        add_repo(name, item)


def list_error(name, message, sid):
    if sid != search_id:
        return
    lists[name]["loading"] = False
    lists[name]["info"].configure(text=message)


def fetch_list(name, url, sid):
    try:
        r = requests.get(url, params=tabs_config[name]["params"], timeout=10)
        if r.status_code == 200:
            data = r.json()
            root.after(0, lambda: show_list(name, data, sid))
        elif r.status_code == 403:
            root.after(0, lambda: list_error(name, "API rate limit exceeded, try later", sid))
        else:
            code = r.status_code
            root.after(0, lambda: list_error(name, f"Error: {code}", sid))
    except requests.RequestException:
        root.after(0, lambda: list_error(name, "Network error, check your connection", sid))


def load_list(name):
    st = lists[name]
    if not st["url"] or st["loaded"] or st["loading"]:
        return
    st["loading"] = True
    st["info"].configure(text="Loading...")
    threading.Thread(target=fetch_list, args=(name, st["url"], search_id), daemon=True).start()


# card tab
def clear_card(message):
    card.update(login=None, page_url=None, loaded=False, loading=False)
    label_card_image.configure(image=blank_image)
    label_card_image.image = blank_image
    label_card_info.configure(text=message)
    card_button.configure(state="disabled")


def find_og_image(page_html, page_url):
    patterns = (
        r'<meta[^>]+property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*property=["\']og:image["\']',
    )
    for p in patterns:
        m = re.search(p, page_html, re.IGNORECASE)
        if m:
            return urljoin(page_url, html.unescape(m.group(1)))
    return None


def show_card(content, sid):
    if sid != search_id:
        return
    try:
        img = Image.open(BytesIO(content)).convert("RGBA")
    except Exception:
        card_error("Could not read the card image", sid)
        return

    w, h = img.size
    ctk_img = ctk.CTkImage(light_image=img, dark_image=img,
                           size=(CARD_WIDTH, round(CARD_WIDTH * h / w)))
    label_card_image.configure(image=ctk_img)
    label_card_image.image = ctk_img

    card["loaded"] = True
    card["loading"] = False
    label_card_info.configure(text="GitFut card")
    card_button.configure(state="normal")


def card_error(message, sid):
    if sid != search_id:
        return
    card["loading"] = False
    label_card_info.configure(text=message)
    card_button.configure(state="normal" if card["page_url"] else "disabled")


def fetch_card(login, sid):
    page_url = f"https://gitfut.com/{login.lower()}"
    try:
        page = requests.get(page_url, headers=HEADERS, timeout=20)
        if page.status_code == 404:
            root.after(0, lambda: card_error("No GitFut card found for this user", sid))
            return
        if page.status_code != 200:
            code = page.status_code
            root.after(0, lambda: card_error(f"GitFut error: {code}", sid))
            return

        img_url = find_og_image(page.text, page_url) or f"{page_url}/opengraph-image"
        img_r = requests.get(img_url, headers=HEADERS, timeout=20)
        if img_r.status_code != 200:
            code = img_r.status_code
            root.after(0, lambda: card_error(f"Card image error: {code}", sid))
            return

        data = img_r.content
        root.after(0, lambda: show_card(data, sid))
    except requests.RequestException:
        root.after(0, lambda: card_error("Network error, check your connection", sid))


def load_card():
    if not card["login"] or card["loaded"] or card["loading"]:
        return
    card["loading"] = True
    label_card_info.configure(text="Loading card... (first time may take a few seconds)")
    threading.Thread(target=fetch_card, args=(card["login"], search_id), daemon=True).start()


def open_gitfut():
    if card["page_url"]:
        webbrowser.open(card["page_url"])


def on_tab_change():
    current = tabview.get()
    if current in tabs_config:
        load_list(current)
    elif current == "GitFut":
        load_card()


# main search stuff
def reset_all(message):
    for name in tabs_config:
        clear_list(name, message)
    clear_card(message)


def reset_fields():
    label_name.configure(text="N/A")
    label_username.configure(text="@N/A")
    label_join.configure(text="Joined N/A")
    label_bio.configure(text="This profile has no bio")
    label_repos_num.configure(text="0")
    label_followers_num.configure(text="0")
    label_following_num.configure(text="0")
    label_location.configure(text="Not Available")
    label_x.configure(text="Not Available")
    label_link.configure(text="Not Available")
    label_company.configure(text="Not Available")
    set_avatar(circle_image())


def show_error(message):
    reset_fields()
    reset_all("No user loaded")
    label_result.configure(text=message, text_color="red")
    search_button.configure(state="normal")


def show_user(user, avatar_bytes):
    label_result.configure(text="")
    label_name.configure(text=shorten(val(user, "name", val(user, "login", "N/A")), 24))
    label_username.configure(text="@" + shorten(val(user, "login", "N/A"), 24))
    label_join.configure(text="Joined " + val(user, "created_at", "N/A")[:4])
    label_bio.configure(text=shorten(val(user, "bio", "This profile has no bio"), 110))
    label_repos_num.configure(text=val(user, "public_repos", "0"))
    label_followers_num.configure(text=val(user, "followers", "0"))
    label_following_num.configure(text=val(user, "following", "0"))
    label_location.configure(text=shorten(val(user, "location"), 26))
    label_x.configure(text=shorten(val(user, "twitter_username"), 17))
    label_link.configure(text=shorten(val(user, "blog"), 26))
    label_company.configure(text=shorten(val(user, "company"), 17))
    set_avatar(circle_image(avatar_bytes))
    search_button.configure(state="normal")

    login = user.get("login")
    lists["Repos"]["url"] = user.get("repos_url")
    lists["Stars"]["url"] = f"https://api.github.com/users/{login}/starred" if login else None
    for name in tabs_config:
        lists[name]["info"].configure(text="Open this tab to load")

    if login:
        card["login"] = login
        card["page_url"] = f"https://gitfut.com/{login.lower()}"
        card_button.configure(state="normal")
        label_card_info.configure(text="Open this tab to load the card")

    on_tab_change()


def fetch_user(username):
    # runs in a thread, so only touch the UI through root.after
    try:
        r = requests.get(f"https://api.github.com/users/{username}", timeout=10)

        if r.status_code == 404:
            root.after(0, lambda: show_error("User not found"))
            return
        if r.status_code == 403:
            root.after(0, lambda: show_error("API rate limit exceeded, try later"))
            return
        if r.status_code != 200:
            code = r.status_code
            root.after(0, lambda: show_error(f"Error: {code}"))
            return

        user = r.json()

        avatar_bytes = None
        if user.get("avatar_url"):
            try:
                a = requests.get(user["avatar_url"], timeout=10)
                if a.status_code == 200:
                    avatar_bytes = a.content
            except requests.RequestException:
                pass

        root.after(0, lambda: show_user(user, avatar_bytes))
    except requests.RequestException:
        root.after(0, lambda: show_error("Network error, check your connection"))


def search_users(event=None):
    global search_id
    username = search_entry.get().strip()
    if not username:
        label_result.configure(text="Please enter a username", text_color="red")
        return

    search_id += 1
    reset_all("Searching...")
    label_result.configure(text="Searching...", text_color="#60abff")
    search_button.configure(state="disabled")
    threading.Thread(target=fetch_user, args=(username,), daemon=True).start()


def load_default_avatar():
    try:
        r = requests.get(DEFAULT_AVATAR, timeout=10)
        content = r.content if r.status_code == 200 else None
    except requests.RequestException:
        content = None
    root.after(0, lambda: set_avatar(circle_image(content)))


# ui
title_label = ctk.CTkLabel(root, text="DevFinder", font=("Courier New", 22, "bold"))
title_label.place(x=200, y=10)

search_entry = ctk.CTkEntry(
    root, placeholder_text="Search Github username", border_width=0,
    width=390, height=60, font=("Courier New", 16), fg_color="#1e2a47",
    placeholder_text_color="#fff", text_color="#fff", corner_radius=15
)
search_entry.place(x=200, y=50)
search_entry.bind("<Return>", search_users)

search_button = ctk.CTkButton(
    root, text="Search", command=search_users, font=("Courier New", 16, "bold"),
    border_width=0, cursor="hand2", width=100, height=60, fg_color="#0079ff",
    hover_color="#60abff", text_color="#fff", corner_radius=15
)
search_button.place(x=600, y=50)

label_result = ctk.CTkLabel(root, text="", width=500, anchor="w", font=("Courier New", 14))
label_result.place(x=205, y=117)

tabview = ctk.CTkTabview(
    root, width=500, height=385, corner_radius=15, fg_color="#1e2a47",
    segmented_button_fg_color="#141d2f",
    segmented_button_selected_color="#0079ff",
    segmented_button_selected_hover_color="#60abff",
    segmented_button_unselected_color="#141d2f",
    segmented_button_unselected_hover_color="#2a3a5f",
    command=on_tab_change
)
tabview.place(x=200, y=155)
tab_profile = tabview.add("Profile")
tab_repos = tabview.add("Repos")
tab_stars = tabview.add("Stars")
tab_card = tabview.add("GitFut")

# profile tab
label_avatar = ctk.CTkLabel(tab_profile, image=circle_image(), text="")
label_avatar.place(x=10, y=10)

label_name = ctk.CTkLabel(tab_profile, text="MaMad", font=("Courier New", 20, "bold"),
                          width=330, anchor="w")
label_name.place(x=130, y=8)

label_username = ctk.CTkLabel(tab_profile, text="@MaMad4Ever", text_color="#0079ff",
                              width=200, anchor="w")
label_username.place(x=130, y=38)

label_join = ctk.CTkLabel(tab_profile, text="Joined 2020", font=("Space Mono", 12),
                          width=120, anchor="e")
label_join.place(x=340, y=38)

label_bio = ctk.CTkLabel(tab_profile, text="This profile has no bio", width=330, height=55,
                         anchor="nw", justify="left", wraplength=330)
label_bio.place(x=130, y=68)

user_stats = ctk.CTkFrame(tab_profile, fg_color="#141d2f", width=440, height=90, corner_radius=15)
user_stats.place(x=20, y=135)

for text, x in (("Repos", 40), ("Followers", 165), ("Following", 315)):
    ctk.CTkLabel(user_stats, text=text, font=("Space Mono", 14)).place(x=x, y=10)

label_repos_num = ctk.CTkLabel(user_stats, text="22", font=("Courier New", 22, "bold"))
label_repos_num.place(x=40, y=38)

label_followers_num = ctk.CTkLabel(user_stats, text="7", font=("Courier New", 22, "bold"))
label_followers_num.place(x=165, y=38)

label_following_num = ctk.CTkLabel(user_stats, text="2", font=("Courier New", 22, "bold"))
label_following_num.place(x=315, y=38)

image_location = ctk.CTkImage(Image.open("./assets/location.png"), size=(22, 22))
ctk.CTkLabel(tab_profile, image=image_location, text="").place(x=15, y=245)
label_location = ctk.CTkLabel(tab_profile, text="Not Available", font=("Space Mono", 14),
                              width=190, anchor="w")
label_location.place(x=45, y=245)

image_x = ctk.CTkImage(Image.open("./assets/x.png"), size=(22, 22))
ctk.CTkLabel(tab_profile, image=image_x, text="").place(x=255, y=245)
label_x = ctk.CTkLabel(tab_profile, text="Not Available", font=("Space Mono", 14),
                       width=170, anchor="w")
label_x.place(x=285, y=245)

image_link = ctk.CTkImage(Image.open("./assets/link.png"), size=(22, 22))
ctk.CTkLabel(tab_profile, image=image_link, text="").place(x=15, y=285)
label_link = ctk.CTkLabel(tab_profile, text="Not Available", font=("Space Mono", 14),
                          width=190, anchor="w")
label_link.place(x=45, y=285)

image_company = ctk.CTkImage(Image.open("./assets/organization.png"), size=(22, 22))
ctk.CTkLabel(tab_profile, image=image_company, text="").place(x=255, y=285)
label_company = ctk.CTkLabel(tab_profile, text="Not Available", font=("Space Mono", 14),
                             width=170, anchor="w")
label_company.place(x=285, y=285)

# repos and stars tabs share the same layout
for name, parent in (("Repos", tab_repos), ("Stars", tab_stars)):
    info = ctk.CTkLabel(parent, text="Search for a user to see their list",
                        font=("Courier New", 14, "bold"), anchor="w")
    info.pack(fill="x", padx=10, pady=(0, 4))

    scroll = ctk.CTkScrollableFrame(parent, fg_color="#1e2a47", width=430, height=270)
    scroll.pack(fill="both", expand=True, padx=2, pady=(0, 2))

    lists[name]["info"] = info
    lists[name]["scroll"] = scroll

# card tab
blank_image = ctk.CTkImage(Image.new("RGBA", (1, 1), (0, 0, 0, 0)), size=(1, 1))

label_card_info = ctk.CTkLabel(tab_card, text="Search for a user to see their FUT card",
                               font=("Courier New", 14, "bold"), anchor="w")
label_card_info.pack(fill="x", padx=10, pady=(0, 4))

label_card_image = ctk.CTkLabel(tab_card, image=blank_image, text="")
label_card_image.pack(pady=(4, 8))

card_button = ctk.CTkButton(tab_card, text="Open on GitFut", command=open_gitfut,
                            font=("Courier New", 14, "bold"), width=180, height=36,
                            fg_color="#0079ff", hover_color="#60abff", cursor="hand2",
                            corner_radius=12, state="disabled")
card_button.pack(pady=(0, 6))

threading.Thread(target=load_default_avatar, daemon=True).start()

root.mainloop()
