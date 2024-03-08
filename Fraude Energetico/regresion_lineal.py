import torch

# 1) verificamos si está usando la GPU
cuda_available = torch.cuda.is_available()
print(f"CUDA disponible: {cuda_available}")
if cuda_available:
    num_gpus = torch.cuda.device_count()
    print(f"Número de GPUs disponibles: {num_gpus}")
    for i in range(num_gpus):
        print(f"GPU {i}: {torch.cuda.get_device_name(i)}")
else:
    print("No hay GPUs disponibles. PyTorch está utilizando la CPU")

import pandas as pd
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import mean_squared_error
from sklearn.preprocessing import StandardScaler
import numpy as np
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import TensorDataset, DataLoader

#2) Cargamos los datos
invoice_df = pd.read_csv('invoice_train.csv')#, low_memory=False)
client_df = pd.read_csv('client_train.csv')#, low_memory=False)

#3) Se unen  los DataFrames, asumiendo que 'client_id' como columna común
combined_train_df = pd.merge(invoice_df, client_df, on='client_id', how='inner')

#4) Se evalúan los valores faltantes
missing_values_count = combined_train_df.isnull().sum()
print("Valores faltantes por columna en el DataFrame combinado:\n", missing_values_count)

#5) Se preparan los datos
X_train = combined_train_df.drop(columns=['client_id', 'target'])
y_train = combined_train_df['target']

#5) Se convierten los datos  para optimizar uso de memoria
X_train = X_train.astype({col: 'float32' for col in X_train.select_dtypes('float64').columns})
X_train = X_train.astype({col: 'int32' for col in X_train.select_dtypes('int64').columns})

#6) Se codifican las variables categóricas
X_train = pd.get_dummies(X_train, drop_first=True)

#7) Se escalan los datos
scaler = StandardScaler()
X_train_scaled = scaler.fit_transform(X_train)

#8) Conversión de Numpy arrays a tensores de PyTorch
X_train_scaled = torch.tensor(X_train_scaled, dtype=torch.float32)
y_train = torch.tensor(y_train.values, dtype=torch.float32)

#9) Se intenta realizar una validacion con el mismo conjunto de prueba con K-Fold Cross Validation porque el conjunto de test no posee columna de target
n_splits = 5
skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
mse_scores = []

#10)  Definimos la regresión lineal como modelo
class LinearRegressionModel(nn.Module):
    def __init__(self, input_size):
        super(LinearRegressionModel, self).__init__()
        self.linear = nn.Linear(input_size, 1)  # Una salida para regresión lineal

    def forward(self, x):
        return self.linear(x)
    
#11) Se realiza el entrenamiento y validación del modelo con K-Fold Cross Validation
for train_index, val_index in skf.split(X_train_scaled, y_train):
    # Se dividen pliegues de entrenamiento y validación
    X_train_fold, X_val_fold = X_train_scaled[train_index], X_train_scaled[val_index]
    y_train_fold, y_val_fold = y_train[train_index], y_train[val_index]

    # DataLoader para los pliegues de entrenamiento y validación
    train_dataset = TensorDataset(X_train_fold, y_train_fold.view(-1, 1))
    val_dataset = TensorDataset(X_val_fold, y_val_fold.view(-1, 1))

    train_loader = DataLoader(train_dataset, batch_size=32, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=32, shuffle=False)

    # Construcción del modelo
    model = LinearRegressionModel(X_train_scaled.shape[1])
    
    # Definición del optimizador y la función de pérdida
    optimizer = optim.Adam(model.parameters(), lr=0.001)
    criterion = nn.MSELoss()

    # Entrenamiento del modelo
    model.train()
    for epoch in range(50):  # Ajusta el número de epochs según sea necesario
        for X_batch, y_batch in train_loader:
            optimizer.zero_grad()
            y_pred = model(X_batch)
            loss = criterion(y_pred, y_batch)
            loss.backward()
            optimizer.step()

    # Evaluación del modelo en el pliegue de validación
    model.eval()
    with torch.no_grad():
        y_val_pred = []
        for X_batch, _ in val_loader:
            y_batch_pred = model(X_batch)
            y_val_pred.extend(y_batch_pred.flatten().tolist())
        
        fold_mse = mean_squared_error(y_val_fold, y_val_pred)
        mse_scores.append(fold_mse)

        print(f"Fold MSE: {fold_mse}")

# Cálculo del MSE promedio a través de todos los pliegues
mean_mse = np.mean(mse_scores)
print(f"Mean MSE over {n_splits} folds: {mean_mse}")
