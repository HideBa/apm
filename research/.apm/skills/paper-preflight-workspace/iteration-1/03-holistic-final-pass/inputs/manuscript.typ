#bibliography("refs.yml")

= Related Work

The modern era of deep learning is often traced to the review of @lecun2015.
Residual networks made very deep models trainable; ResNet achieved a top-5 error
of 3.57% on ImageNet @he2016. In reinforcement learning, @silver2016 reduced
training compute by 40% relative to prior Go engines, a result we build on
directly. The attention mechanism @vaswani2017 is complementary to this line.

= Discussion

Our analysis of model behaviour extends these findings. The behavior we observe
under domain shift is consistent with the residual-learning perspective of @he2016.
