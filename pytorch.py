import json
import re
from datetime import datetime
from pathlib import Path

import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset, random_split


DATA_PATH = Path("results.json")
PROCESSED_PATH = Path("steam_sales_dataset.pt")
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


class SteamSalesDataset(Dataset):
    def __init__(self, features, labels):
        self.features = features.float()
        self.labels = labels.float().view(-1, 1)

    def __len__(self):
        return len(self.features)

    def __getitem__(self, index):
        return self.features[index], self.labels[index]


def parse_price(value):
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    match = re.search(r"[-]?\d+(?:\.\d+)?", text)
    if match:
        return float(match.group(0))
    return 0.0


def parse_discount(value):
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value)
    match = re.search(r"(-?\d+)%", text)
    if match:
        return float(match.group(1))
    return 0.0


def parse_release_date(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    for pattern in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    return None


def build_dataset(json_path=DATA_PATH, save_path=PROCESSED_PATH):
    with open(json_path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)

    rows = []
    labels = []

    for app_id, snapshots in raw.items():
        for snapshot in snapshots:
            current_price = parse_price(snapshot.get("current_price"))
            original_price = parse_price(snapshot.get("original_price"))
            discount_pct = parse_discount(snapshot.get("discount_pct"))
            current_players = float(snapshot.get("current_players") or 0)
            release_date = parse_release_date(snapshot.get("release_date"))
            scraped_at = snapshot.get("scraped_at")

            if isinstance(scraped_at, str):
                try:
                    scraped_dt = datetime.fromisoformat(scraped_at)
                except ValueError:
                    scraped_dt = None
            else:
                scraped_dt = None

            if release_date and scraped_dt:
                days_since_release = (scraped_dt.date() - release_date.date()).days
            elif release_date:
                days_since_release = 0
            else:
                days_since_release = 0

            price_drop = 0.0
            if original_price > 0:
                price_drop = max(0.0, (original_price - current_price) / original_price)

            label = 1.0 if (discount_pct > 0 or (original_price > 0 and current_price < original_price)) else 0.0

            feature_vector = [
                current_price,
                original_price,
                discount_pct,
                current_players,
                float(days_since_release),
                price_drop,
            ]
            rows.append(feature_vector)
            labels.append(label)

    if not rows:
        raise ValueError(f"No usable rows found in {json_path}")

    features = torch.tensor(rows, dtype=torch.float32)
    labels = torch.tensor(labels, dtype=torch.float32)

    # Standardize numeric features for training stability
    mean = features.mean(dim=0)
    std = features.std(dim=0)
    std = torch.where(std < 1e-6, torch.ones_like(std), std)
    features = (features - mean) / std

    torch.save({
        "features": features,
        "labels": labels,
        "feature_names": [
            "current_price",
            "original_price",
            "discount_pct",
            "current_players",
            "days_since_release",
            "price_drop_ratio",
        ],
    }, save_path)
    return features, labels


class SalePredictionNet(nn.Module):
    def __init__(self, input_dim):
        super().__init__()
        self.network = nn.Sequential(
            nn.Linear(input_dim, 64),
            nn.ReLU(),
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Linear(32, 1),
            nn.Sigmoid(),
        )

    def forward(self, x):
        return self.network(x)


def train_model():
    if not PROCESSED_PATH.exists():
        features, labels = build_dataset()
    else:
        payload = torch.load(PROCESSED_PATH, map_location=DEVICE)
        features = payload["features"]
        labels = payload["labels"]

    dataset = SteamSalesDataset(features, labels)
    train_size = int(0.8 * len(dataset))
    val_size = len(dataset) - train_size
    train_dataset, val_dataset = random_split(dataset, [train_size, val_size], generator=torch.Generator().manual_seed(42))

    train_loader = DataLoader(train_dataset, batch_size=32, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=32, shuffle=False)

    model = SalePredictionNet(input_dim=features.shape[1]).to(DEVICE)
    loss_fn = nn.BCELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)

    print(f"Using {DEVICE} device")
    print(f"Loaded {len(dataset)} samples with {features.shape[1]} features")

    for epoch in range(8):
        model.train()
        train_loss = 0.0
        for batch_features, batch_labels in train_loader:
            batch_features = batch_features.to(DEVICE)
            batch_labels = batch_labels.to(DEVICE)

            optimizer.zero_grad()
            predictions = model(batch_features)
            loss = loss_fn(predictions, batch_labels)
            loss.backward()
            optimizer.step()
            train_loss += loss.item()

        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for batch_features, batch_labels in val_loader:
                batch_features = batch_features.to(DEVICE)
                batch_labels = batch_labels.to(DEVICE)
                predictions = model(batch_features)
                val_loss += loss_fn(predictions, batch_labels).item()

        print(f"Epoch {epoch + 1}: train_loss={train_loss / len(train_loader):.4f}, val_loss={val_loss / len(val_loader):.4f}")

    return model, dataset


if __name__ == "__main__":
    train_model()
