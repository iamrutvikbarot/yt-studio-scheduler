import os
import requests

def check_link():
    fb_page_id = input("Enter FB_PAGE_ID: ").strip()
    fb_token = input("Enter FB_PAGE_ACCESS_TOKEN: ").strip()

    url = f"https://graph.facebook.com/v19.0/{fb_page_id}?fields=name,id,instagram_business_account&access_token={fb_token}"
    res = requests.get(url).json()

    print("\n=======================================================")
    print(f"Facebook Page: {res.get('name')} (ID: {res.get('id')})")
    
    ig_account = res.get("instagram_business_account")
    if ig_account and "id" in ig_account:
        ig_id = ig_account["id"]
        print(f"✅ Instagram Linked! IG_USER_ID: {ig_id}")
        print("=======================================================")
        print("Here are your Meta secrets for GitHub:")
        print(f"FB_PAGE_ID:            {fb_page_id}")
        print(f"FB_PAGE_ACCESS_TOKEN:  {fb_token}")
        print(f"IG_USER_ID:            {ig_id}")
        print(f"IG_ACCESS_TOKEN:       {fb_token}")
        print("=======================================================\n")
    else:
        print("⚠️ No Instagram Professional account linked to this page yet.")
        print("Please link your Instagram to this Facebook Page:")
        print("👉 In Instagram App: Edit Profile -> Page -> Select your Page")
        print("=======================================================\n")

if __name__ == "__main__":
    check_link()
