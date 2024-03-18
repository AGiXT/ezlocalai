from deepseek_vl.models import VLChatProcessor
from transformers import AutoModelForCausalLM
from datetime import datetime
import requests
import torch
import PIL.Image
import uuid
import tiktoken
import os


def get_tokens(text: str) -> int:
    encoding = tiktoken.get_encoding("cl100k_base")
    num_tokens = len(encoding.encode(text))
    return num_tokens


class VLM:
    def __init__(self, model="deepseek-ai/deepseek-vl-1.3b-chat"):
        self.model = model.split("/")[-1]
        os.makedirs(os.path.join(os.getcwd(), "outputs"), exist_ok=True)
        try:
            self.vl_chat_processor = VLChatProcessor.from_pretrained(model)
            self.tokenizer = self.vl_chat_processor.tokenizer
            self.vl_gpt = AutoModelForCausalLM.from_pretrained(
                model, trust_remote_code=True
            )
            self.vl_gpt = self.vl_gpt.to(torch.bfloat16).cuda().eval()
        except:
            self.vl_chat_processor = None
            self.tokenizer = None
            self.vl_gpt = None

    def chat(self, messages, **kwargs):
        pil_images = []
        images = []
        conversation = []
        for message in messages:
            if isinstance(message["content"], list):
                if "image_url" in message["content"][0]:
                    url = message["content"][0]["image_url"]
                    image_path = f"./outputs/{uuid.uuid4().hex}.jpg"
                    if url.startswith("http"):
                        image = requests.get(url).content
                        with open(image_path, "wb") as f:
                            f.write(image)
                        images.append(image_path)
                    else:
                        with open(image_path, "wb") as f:
                            f.write(url)
                        images.append(image_path)
                    pil_img = PIL.Image.open(image_path)
                    pil_img = pil_img.convert("RGB")
                    pil_images.append(pil_img)
                for msg in message["content"]:
                    if "text" in msg:
                        conversation.append(
                            {
                                "role": message["role"],
                                "content": "<image_placeholder>" + msg["text"],
                            }
                        )
        conversation[-1]["images"] = images
        conversation.append({"role": "Assistant", "content": ""})
        prepare_inputs = self.vl_chat_processor(
            conversations=conversation, images=pil_images, force_batchify=True
        ).to(self.vl_gpt.device)
        inputs_embeds = self.vl_gpt.prepare_inputs_embeds(**prepare_inputs)
        outputs = self.vl_gpt.language_model.generate(
            inputs_embeds=inputs_embeds,
            attention_mask=prepare_inputs.attention_mask,
            pad_token_id=self.tokenizer.eos_token_id,
            bos_token_id=self.tokenizer.bos_token_id,
            eos_token_id=self.tokenizer.eos_token_id,
            max_new_tokens=512 if "max_tokens" not in kwargs else kwargs["max_tokens"],
            do_sample=False,
            use_cache=True,
        )
        answer = self.tokenizer.decode(
            outputs[0].cpu().tolist(), skip_special_tokens=True
        )
        completion_tokens = get_tokens(answer)
        prompt_tokens = get_tokens(
            " ".join([message["content"] for message in conversation])
        )
        total_tokens = completion_tokens + prompt_tokens
        data = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "index": 0,
                    "message": {"content": answer, "role": "assistant"},
                    "logprobs": None,
                }
            ],
            "created": datetime.now().isoformat(),
            "id": f"chatcmpl-{uuid.uuid4().hex}",
            "model": self.model,
            "object": "chat.completion",
            "usage": {
                "completion_tokens": completion_tokens,
                "prompt_tokens": prompt_tokens,
                "total_tokens": total_tokens,
            },
        }
        return data

    def describe_image(self, image_url):
        messages = [
            {
                "role": "User",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": image_url,
                    },
                    {
                        "type": "text",
                        "text": "Describe each stage of this image.",
                    },
                ],
            },
        ]
        response = self.chat(
            messages=messages,
        )
        return response["choices"][0]["message"]["content"]