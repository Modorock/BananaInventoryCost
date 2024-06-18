import requests
from collections import Counter
from time import sleep, time
from prettytable import PrettyTable
from datetime import datetime
import os
import glob
from colorama import Fore, Style, init

init(autoreset=True)

TOKEN_BUCKET_CAPACITY = 5
TOKEN_REFILL_INTERVAL = 1.5
tokens = TOKEN_BUCKET_CAPACITY
last_refill_time = time()
request_queue = []

def refill_tokens():
    global tokens, last_refill_time
    current_time = time()
    elapsed_time = current_time - last_refill_time
    tokens = min(TOKEN_BUCKET_CAPACITY, tokens + (elapsed_time / TOKEN_REFILL_INTERVAL))
    last_refill_time = current_time

def fetch_inventory(steam_id, app_id, context_id):
    url = f"https://steamcommunity.com/inventory/{steam_id}/{app_id}/{context_id}?l=english&count=5000"
    response = requests.get(url)
    response.raise_for_status()
    return response.json()

def extract_classid_assets(inventory_data):
    assets = inventory_data.get("assets", [])
    asset_classids = [item["classid"] for item in assets]
    return asset_classids

def extract_classid_descriptions(inventory_data):
    descriptions = inventory_data.get("descriptions", [])
    descriptions_classids = [item["classid"] for item in descriptions]
    return descriptions_classids

def extract_name(inventory_data):
    descriptions = inventory_data.get("descriptions", [])
    banana_names = {item["classid"]: item["name"] for item in descriptions }
    filtered_names = {classid: name for classid, name in banana_names.items() if name != 'Banana'}
    return filtered_names

def count_classid_occurrences(classid_list):
    classid_counts = Counter(classid_list)
    return classid_counts

def fetch_item_price_with_retry(market_hash_name, app_id):
    global tokens, last_refill_time

    if time() - last_refill_time > TOKEN_REFILL_INTERVAL:
        refill_tokens()

    if tokens < 1:
        print(f"Too many requests. Retrying in {TOKEN_REFILL_INTERVAL} seconds.")
        request_queue.append((market_hash_name, app_id))
        sleep(TOKEN_REFILL_INTERVAL)
        return "Price not available"
    
    url = f"https://steamcommunity.com/market/priceoverview/?currency=1&appid={app_id}&market_hash_name={market_hash_name}"
    retry_attempts = 4
    delay = 15
    
    for attempt in range(retry_attempts):
        try:
            response = requests.get(url)
            response.raise_for_status()
            price_data = response.json()
            lowest_price = price_data.get("lowest_price")

            if not lowest_price:
                print(f"No price available for {market_hash_name}")

            tokens -= 1

            if request_queue:
                queued_request = request_queue.pop(0)
                fetch_item_price_with_retry(*queued_request)
            
            sleep(1.5)

            return lowest_price

        except requests.exceptions.RequestException as e:
            if response.status_code == 429:
                print(f"Too many requests. Retrying in {delay} seconds.")
                sleep(delay)
            else:
                print(f"Error fetching price for {market_hash_name}: {e}")
                sleep(10)
                continue

    print(f"Failed to fetch price for {market_hash_name} after {retry_attempts} attempts.")
    return "Price not available"

def convert_usd_to_uah(usd_price):
    return usd_price * 40

def read_previous_prices(steam_id):
    files = glob.glob(f"banana_Price_{steam_id}_*.txt")
    if not files:
        return {}
    
    latest_file = max(files, key=os.path.getctime)
    previous_prices = {}

    with open(latest_file, "r", encoding="utf-8") as file:
        lines = file.readlines()
        for line in lines:
            if line.startswith("|"):
                parts = line.split("|")
                if len(parts) > 3:
                    item_name = parts[1].strip()
                    price_per_one = parts[3].strip()
                    previous_prices[item_name] = price_per_one

    return previous_prices

def main():
    # Write your steam id.
    steam_id = '7656***********3347' 
    app_id = "2923300"
    context_id = "2"

    previous_prices = read_previous_prices(steam_id)

    try:
        inventory_data = fetch_inventory(steam_id, app_id, context_id)
        asset_classids = extract_classid_assets(inventory_data)
        banana_names = extract_name(inventory_data)
        filtered_classids = [classid for classid in asset_classids if classid in banana_names]
        asset_classid_counts = count_classid_occurrences(filtered_classids)

        market_hash_names = [item["market_hash_name"] for item in inventory_data.get("descriptions", []) if "market_hash_name" in item]
        prices = {}
        for name in market_hash_names:
            try:
                print(f"Fetching price for {name}...")
                lowest_price = fetch_item_price_with_retry(name, app_id)
                prices[name] = lowest_price
            except requests.exceptions.RequestException as e:
                print(f"Error fetching price for {name}: {e}")
                prices[name] = "Error fetching price"

        count_prices_table = PrettyTable()
        count_prices_table.field_names = ["Item Name", "Count", "Price per One (USD)", "Price per One (UAH)", "Price for All (USD)", "Price for All (UAH)", "Change"]
        total_usd = 0
        total_uah = 0
        table_rows = []
        for name, price_data in prices.items():
            count = next((key for key, value in banana_names.items() if value == name), None)
            if count is None:
                print(f"No match found for name: {name}")
                count = 0
                usd_price = 0.0
            else:
                count = asset_classid_counts[count]
                
            if price_data != "Price not available" and price_data != "Error fetching price":
                try:
                    usd_price = float(price_data.split()[0].replace('$', ''))
                    uah_price = convert_usd_to_uah(usd_price)
                    total_price_usd = usd_price * count
                    total_price_uah = convert_usd_to_uah(total_price_usd)
                    total_usd += total_price_usd
                    total_uah += total_price_uah

                    change = ""
                    previous_price = previous_prices.get(name)

                    usd_price_str = f"${usd_price:.2f}"
                    uah_price_str = f"UAH {uah_price:.2f}"

                    if previous_price is not None:
                        try:
                            previous_usd_price = float(previous_price.split()[0].replace('$', ''))
                            if usd_price > previous_usd_price:
                                change = Fore.GREEN + "▲" + Style.RESET_ALL
                            elif usd_price < previous_usd_price:
                                change = Fore.RED + "▼" + Style.RESET_ALL
                            else:
                                change = ""
                        except ValueError as ve:
                            print(f"Error converting price for {name}: {ve}")
                            change = ""

                    total_price_usd_str = f"${total_price_usd:.2f}"
                    total_price_uah_str = f"UAH {total_price_uah:.2f}"

                    table_rows.append([
                        f"{name}",
                        f"{str(count)}",
                        usd_price_str,
                        uah_price_str,
                        total_price_usd_str,
                        total_price_uah_str,
                        change
                    ])
                except ValueError as ve:
                    print(f"Error converting price for {name}: {ve}")

        total_value_table = PrettyTable()
        total_value_table.field_names = ["Total Inventory Value (USD)", "Total Inventory Value (UAH)"]

        for row in table_rows:
            count_prices_table.add_row(row)

        count_prices_table.sortby = "Price for All (USD)"
        count_prices_table.reversesort = True

        total_value_table.add_row([
            f"${total_usd:.2f}",
            f"UAH {total_uah:.2f}",])

        print(count_prices_table)
        print(total_value_table)

        current_date = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        file_name = f"banana_Price_{steam_id}_{current_date}.txt"

        with open(file_name, 'w', encoding='utf-8') as file:
            file.write(str(count_prices_table) + "\n")
            file.write(str(total_value_table) + "\n")

    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
